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
import docx
import re
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
import asyncio
import shutil
import wave
import struct
import math

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
    audio_duration: Optional[float] = None
    aligned_segments: Optional[List[dict]] = None
    user_corrections: Optional[List[dict]] = None

class TimingCorrection(BaseModel):
    segment_index: int
    word_index: int
    new_start_time: float
    new_end_time: float

def get_audio_duration(file_path: str) -> float:
    """Get audio duration from WAV file"""
    try:
        with wave.open(file_path, 'rb') as audio_file:
            frames = audio_file.getnframes()
            sample_rate = audio_file.getframerate()
            duration = frames / float(sample_rate)
            return duration
    except Exception as e:
        logging.error(f"Error getting audio duration: {e}")
        return 120.0  # Default to 2 minutes

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

def create_segments_from_text(text: str, audio_duration: float) -> List[dict]:
    """Create evenly spaced segments from text"""
    words = clean_text(text).split()
    total_words = len(words)
    
    if total_words == 0:
        return []
    
    time_per_word = audio_duration / total_words if total_words > 0 else 1.0
    
    segments = []
    current_time = 0
    
    # Group words into segments of roughly 5-10 words each
    words_per_segment = 7  # Target average
    current_segment = []
    current_segment_words = []
    
    for i, word in enumerate(words):
        current_segment.append(word)
        current_segment_words.append({
            'word': word,
            'start': round(current_time, 1),
            'end': round(current_time + time_per_word, 1),
            'confidence': 0.8
        })
        current_time += time_per_word
        
        # Create a new segment when we reach the target size or at the end
        if len(current_segment) >= words_per_segment or i == len(words) - 1:
            if current_segment:
                segment_text = ' '.join(current_segment)
                segments.append({
                    'start': round(current_segment_words[0]['start'], 1),
                    'end': round(current_segment_words[-1]['end'], 1),
                    'text': segment_text,
                    'words': current_segment_words
                })
                current_segment = []
                current_segment_words = []
    
    return segments

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
    lrc_content += f"[by:Auto-Timing]\n\n"
    
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
        
        # Create project directory for permanent storage
        project_dir = ROOT_DIR / "projects" / project.id
        project_dir.mkdir(parents=True, exist_ok=True)
        
        audio_path = project_dir / audio_file.filename
        text_path = project_dir / text_file.filename
        
        with open(audio_path, 'wb') as f:
            shutil.copyfileobj(audio_file.file, f)
        
        with open(text_path, 'wb') as f:
            shutil.copyfileobj(text_file.file, f)
        
        # Start processing in background
        asyncio.create_task(process_audio_text(project.id, str(audio_path), str(text_path), str(project_dir)))
        
        return {"project_id": project.id, "status": "processing"}
        
    except Exception as e:
        logging.error(f"Error uploading files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def process_audio_text(project_id: str, audio_path: str, text_path: str, project_dir: str):
    """Process audio and text files asynchronously"""
    try:
        # Extract text from file
        original_text = extract_text_from_file(text_path)
        original_text = clean_text(original_text)
        
        # Get audio duration
        audio_duration = get_audio_duration(audio_path)
        
        # Create segments with evenly spaced timing
        segments = create_segments_from_text(original_text, audio_duration)
        
        # Update project in database
        await db.projects.update_one(
            {"id": project_id},
            {
                "$set": {
                    "audio_duration": audio_duration,
                    "aligned_segments": segments,
                    "status": "completed"
                }
            }
        )
        
        # No need to clean up - we're keeping the files
        logging.info(f"Project {project_id} processed successfully")
        
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
    # Convert MongoDB documents to dictionaries and handle ObjectId
    return [
        {k: str(v) if k == "_id" else v for k, v in project.items()}
        for project in projects
    ]

@api_router.get("/projects/{project_id}")
async def get_project(project_id: str):
    """Get specific project"""
    project = await db.projects.find_one({"id": project_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    # Convert MongoDB document to dictionary and handle ObjectId
    return {k: str(v) if k == "_id" else v for k, v in project.items()}

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

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()