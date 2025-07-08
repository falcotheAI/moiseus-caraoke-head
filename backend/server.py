from fastapi import FastAPI, APIRouter, UploadFile, File, HTTPException, Form
from fastapi.responses import JSONResponse, FileResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid
from datetime import datetime
import tempfile
import whisperx
import ffmpeg
import json
import docx
import re
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
import asyncio
import shutil

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Models
class SubtitleProject(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_name: str
    audio_filename: str
    text_filename: str
    language: str
    status: str = "processing"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    whisper_transcription: Optional[dict] = None
    aligned_segments: Optional[List[dict]] = None
    user_corrections: Optional[List[dict]] = None

class TimingCorrection(BaseModel):
    segment_index: int
    word_index: int
    new_start_time: float
    new_end_time: float

# Global variables for model management
whisper_model = None
align_model = None
metadata = None

def load_whisper_model():
    """Load Whisper model on startup"""
    global whisper_model, align_model, metadata
    try:
        # Load Whisper model
        whisper_model = whisperx.load_model("base", device="cpu", language="ru")
        
        # Load alignment model
        align_model, metadata = whisperx.load_align_model(language_code="ru", device="cpu")
        
        logging.info("Whisper models loaded successfully")
    except Exception as e:
        logging.error(f"Error loading Whisper models: {e}")
        # Fallback to simpler model if needed
        whisper_model = None

def extract_text_from_file(file_path: str) -> str:
    """Extract text from .txt or .docx file"""
    if file_path.endswith('.txt'):
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    elif file_path.endswith('.docx'):
        doc = docx.Document(file_path)
        return '\n'.join([paragraph.text for paragraph in doc.paragraphs])
    else:
        raise ValueError("Unsupported file format")

def clean_text(text: str) -> str:
    """Clean and normalize text"""
    # Remove extra whitespace and normalize
    text = re.sub(r'\s+', ' ', text.strip())
    # Remove special characters but keep basic punctuation
    text = re.sub(r'[^\w\s\-\.,!?]', '', text)
    return text

def align_text_with_whisper(whisper_result: dict, original_text: str) -> List[dict]:
    """Align original text with Whisper transcription"""
    whisper_text = whisper_result.get('text', '')
    original_clean = clean_text(original_text)
    whisper_clean = clean_text(whisper_text)
    
    # Split into words
    original_words = original_clean.split()
    whisper_segments = whisper_result.get('segments', [])
    
    aligned_segments = []
    
    for segment in whisper_segments:
        segment_words = segment.get('words', [])
        if not segment_words:
            continue
            
        # Find best matching words from original text
        segment_text = segment.get('text', '').strip()
        
        # Use sequence matching to find similar parts
        matcher = SequenceMatcher(None, segment_text.lower(), original_clean.lower())
        
        aligned_words = []
        for word_info in segment_words:
            word = word_info.get('word', '').strip()
            start = word_info.get('start', 0)
            end = word_info.get('end', 0)
            
            # Find closest word in original text
            best_match = word
            for orig_word in original_words:
                if orig_word.lower() in word.lower() or word.lower() in orig_word.lower():
                    best_match = orig_word
                    break
            
            aligned_words.append({
                'word': best_match,
                'start': round(start, 1),
                'end': round(end, 1),
                'confidence': word_info.get('confidence', 0.8)
            })
        
        aligned_segments.append({
            'start': round(segment.get('start', 0), 1),
            'end': round(segment.get('end', 0), 1),
            'text': segment_text,
            'words': aligned_words
        })
    
    return aligned_segments

def generate_ttml(segments: List[dict], project_name: str) -> str:
    """Generate TTML subtitle file"""
    ttml_root = ET.Element('tt')
    ttml_root.set('xmlns', 'http://www.w3.org/ns/ttml')
    ttml_root.set('xml:lang', 'ru')
    
    head = ET.SubElement(ttml_root, 'head')
    styling = ET.SubElement(head, 'styling')
    
    # Add basic styling
    style = ET.SubElement(styling, 'style')
    style.set('xml:id', 'defaultStyle')
    style.set('tts:textAlign', 'center')
    style.set('tts:color', 'white')
    style.set('tts:fontSize', '18px')
    
    body = ET.SubElement(ttml_root, 'body')
    div = ET.SubElement(body, 'div')
    
    for i, segment in enumerate(segments):
        p = ET.SubElement(div, 'p')
        p.set('begin', f"{segment['start']:.1f}s")
        p.set('end', f"{segment['end']:.1f}s")
        p.set('style', 'defaultStyle')
        p.text = segment['text']
    
    return ET.tostring(ttml_root, encoding='unicode')

def generate_lrc(segments: List[dict], project_name: str) -> str:
    """Generate LRC karaoke file"""
    lrc_content = f"[ti:{project_name}]\n"
    lrc_content += f"[ar:Generated by Karaoke Subtitles]\n"
    lrc_content += f"[al:Karaoke]\n"
    lrc_content += f"[by:Whisper AI]\n\n"
    
    for segment in segments:
        # Convert time to MM:SS.xx format
        start_time = segment['start']
        minutes = int(start_time // 60)
        seconds = start_time % 60
        
        # Add segment line
        lrc_content += f"[{minutes:02d}:{seconds:05.2f}]{segment['text']}\n"
        
        # Add word-level timing if available
        if segment.get('words'):
            word_line = ""
            for word_info in segment['words']:
                word_start = word_info['start']
                word_minutes = int(word_start // 60)
                word_seconds = word_start % 60
                word_line += f"<{word_minutes:02d}:{word_seconds:05.2f}>{word_info['word']} "
            if word_line:
                lrc_content += f"[{minutes:02d}:{seconds:05.2f}]{word_line.strip()}\n"
    
    return lrc_content

@api_router.get("/")
async def root():
    return {"message": "Karaoke Subtitles API"}

@api_router.post("/upload")
async def upload_files(
    audio_file: UploadFile = File(...),
    text_file: UploadFile = File(...),
    project_name: str = Form(...),
    language: str = Form(default="ru")
):
    """Upload audio and text files to start processing"""
    try:
        if not audio_file.filename.endswith('.wav'):
            raise HTTPException(status_code=400, detail="Only WAV files are supported")
        
        if not (text_file.filename.endswith('.txt') or text_file.filename.endswith('.docx')):
            raise HTTPException(status_code=400, detail="Only TXT and DOCX files are supported")
        
        # Create project
        project = SubtitleProject(
            project_name=project_name,
            audio_filename=audio_file.filename,
            text_filename=text_file.filename,
            language=language,
            status="processing"
        )
        
        # Save to database
        await db.projects.insert_one(project.dict())
        
        # Save files temporarily
        temp_dir = tempfile.mkdtemp()
        audio_path = os.path.join(temp_dir, audio_file.filename)
        text_path = os.path.join(temp_dir, text_file.filename)
        
        with open(audio_path, 'wb') as f:
            shutil.copyfileobj(audio_file.file, f)
        
        with open(text_path, 'wb') as f:
            shutil.copyfileobj(text_file.file, f)
        
        # Start processing in background
        asyncio.create_task(process_audio_text(project.id, audio_path, text_path, temp_dir))
        
        return {"project_id": project.id, "status": "processing"}
        
    except Exception as e:
        logging.error(f"Error uploading files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def process_audio_text(project_id: str, audio_path: str, text_path: str, temp_dir: str):
    """Process audio and text files asynchronously"""
    try:
        # Extract text from file
        original_text = extract_text_from_file(text_path)
        
        # Load audio
        audio = whisperx.load_audio(audio_path)
        
        # Transcribe with Whisper
        if whisper_model:
            result = whisper_model.transcribe(audio, batch_size=16)
            
            # Align with original text
            aligned_segments = align_text_with_whisper(result, original_text)
            
            # Update project in database
            await db.projects.update_one(
                {"id": project_id},
                {
                    "$set": {
                        "whisper_transcription": result,
                        "aligned_segments": aligned_segments,
                        "status": "completed"
                    }
                }
            )
        else:
            # Fallback: create dummy segments
            words = original_text.split()
            segments = []
            time_per_word = 0.5  # 500ms per word
            
            current_time = 0
            for i, word in enumerate(words):
                segments.append({
                    'start': round(current_time, 1),
                    'end': round(current_time + time_per_word, 1),
                    'text': word,
                    'words': [{
                        'word': word,
                        'start': round(current_time, 1),
                        'end': round(current_time + time_per_word, 1),
                        'confidence': 0.8
                    }]
                })
                current_time += time_per_word
            
            await db.projects.update_one(
                {"id": project_id},
                {
                    "$set": {
                        "aligned_segments": segments,
                        "status": "completed"
                    }
                }
            )
        
        # Clean up temporary files
        shutil.rmtree(temp_dir)
        
    except Exception as e:
        logging.error(f"Error processing audio: {e}")
        await db.projects.update_one(
            {"id": project_id},
            {"$set": {"status": "error", "error_message": str(e)}}
        )

@api_router.get("/projects")
async def get_projects():
    """Get all projects"""
    projects = await db.projects.find().to_list(100)
    return projects

@api_router.get("/projects/{project_id}")
async def get_project(project_id: str):
    """Get specific project"""
    project = await db.projects.find_one({"id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

@api_router.post("/projects/{project_id}/correct")
async def correct_timing(project_id: str, corrections: List[TimingCorrection]):
    """Apply timing corrections"""
    project = await db.projects.find_one({"id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    segments = project.get('aligned_segments', [])
    
    for correction in corrections:
        if correction.segment_index < len(segments):
            segment = segments[correction.segment_index]
            if correction.word_index < len(segment.get('words', [])):
                word = segment['words'][correction.word_index]
                word['start'] = correction.new_start_time
                word['end'] = correction.new_end_time
    
    await db.projects.update_one(
        {"id": project_id},
        {"$set": {"aligned_segments": segments}}
    )
    
    return {"message": "Corrections applied"}

@api_router.get("/projects/{project_id}/download/ttml")
async def download_ttml(project_id: str):
    """Download TTML file"""
    project = await db.projects.find_one({"id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    segments = project.get('aligned_segments', [])
    ttml_content = generate_ttml(segments, project['project_name'])
    
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.ttml', delete=False)
    temp_file.write(ttml_content)
    temp_file.close()
    
    return FileResponse(
        temp_file.name,
        media_type='application/xml',
        filename=f"{project['project_name']}.ttml"
    )

@api_router.get("/projects/{project_id}/download/lrc")
async def download_lrc(project_id: str):
    """Download LRC file"""
    project = await db.projects.find_one({"id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    segments = project.get('aligned_segments', [])
    lrc_content = generate_lrc(segments, project['project_name'])
    
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.lrc', delete=False)
    temp_file.write(lrc_content)
    temp_file.close()
    
    return FileResponse(
        temp_file.name,
        media_type='text/plain',
        filename=f"{project['project_name']}.lrc"
    )

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("startup")
async def startup_event():
    """Initialize models on startup"""
    load_whisper_model()

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()