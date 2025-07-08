import requests
import os
import time
import unittest
from pathlib import Path

# Get the backend URL from the frontend .env file
BACKEND_URL = "https://aec9f70a-74b1-4f00-aa66-f31b5a98a3d7.preview.emergentagent.com"
API_URL = f"{BACKEND_URL}/api"

class KaraokeSubtitlesAPITest(unittest.TestCase):
    """Test the Karaoke Subtitles API endpoints"""
    
    def setUp(self):
        """Set up test data"""
        self.project_name = f"Test Project {int(time.time())}"
        self.test_files_dir = Path(__file__).parent / "test_files"
        self.test_files_dir.mkdir(exist_ok=True)
        
        # Create test audio file if it doesn't exist
        self.audio_file_path = self.test_files_dir / "test_audio.wav"
        if not self.audio_file_path.exists():
            self._create_test_wav_file(self.audio_file_path)
        
        # Create test text file if it doesn't exist
        self.text_file_path = self.test_files_dir / "test_lyrics.txt"
        if not self.text_file_path.exists():
            with open(self.text_file_path, "w") as f:
                f.write("This is a test lyric file\nWith multiple lines\nFor testing karaoke subtitles")
        
        self.project_id = None
    
    def _create_test_wav_file(self, file_path):
        """Create a simple test WAV file"""
        try:
            import wave
            import struct
            import numpy as np
            
            # Create a 3-second silent WAV file
            duration = 3  # seconds
            sample_rate = 44100
            num_samples = duration * sample_rate
            
            with wave.open(str(file_path), 'w') as wav_file:
                wav_file.setnchannels(1)  # Mono
                wav_file.setsampwidth(2)  # 2 bytes per sample
                wav_file.setframerate(sample_rate)
                
                # Generate silent audio (zeros)
                for i in range(num_samples):
                    value = 0
                    packed_value = struct.pack('h', value)
                    wav_file.writeframes(packed_value)
            
            print(f"Created test WAV file at {file_path}")
        except Exception as e:
            print(f"Error creating test WAV file: {e}")
            # Create an empty file as fallback
            with open(file_path, "wb") as f:
                f.write(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88\x58\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00")
    
    def test_01_api_root(self):
        """Test the API root endpoint"""
        print("\n--- Testing API Root ---")
        response = requests.get(f"{API_URL}/")
        print(f"Response: {response.status_code} - {response.text}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("message", response.json())
    
    def test_02_upload_files(self):
        """Test file upload functionality"""
        print("\n--- Testing File Upload ---")
        
        # Skip if test files don't exist
        if not self.audio_file_path.exists() or not self.text_file_path.exists():
            self.skipTest("Test files not available")
        
        with open(self.audio_file_path, "rb") as audio_file, open(self.text_file_path, "rb") as text_file:
            files = {
                "audio_file": ("test_audio.wav", audio_file, "audio/wav"),
                "text_file": ("test_lyrics.txt", text_file, "text/plain")
            }
            data = {
                "project_name": self.project_name,
                "language": "en"
            }
            
            response = requests.post(f"{API_URL}/upload", files=files, data=data)
            print(f"Upload response: {response.status_code} - {response.text}")
            
            self.assertEqual(response.status_code, 200)
            response_data = response.json()
            self.assertIn("project_id", response_data)
            self.assertIn("status", response_data)
            self.assertEqual(response_data["status"], "processing")
            
            # Save project ID for subsequent tests
            self.__class__.project_id = response_data["project_id"]
            print(f"Created project with ID: {self.__class__.project_id}")
    
    def test_03_get_projects(self):
        """Test getting all projects"""
        print("\n--- Testing Get Projects ---")
        response = requests.get(f"{API_URL}/projects")
        print(f"Get projects response: {response.status_code}")
        
        self.assertEqual(response.status_code, 200)
        projects = response.json()
        self.assertIsInstance(projects, list)
        
        if projects:
            print(f"Found {len(projects)} projects")
            # Print details of the first project
            print(f"Sample project: {projects[0]}")
    
    def test_04_wait_for_processing(self):
        """Wait for project processing to complete"""
        if not hasattr(self.__class__, 'project_id') or not self.__class__.project_id:
            self.skipTest("No project ID available from upload test")
        
        print(f"\n--- Waiting for project {self.__class__.project_id} to complete processing ---")
        max_attempts = 10
        attempt = 0
        project_completed = False
        
        while attempt < max_attempts and not project_completed:
            attempt += 1
            response = requests.get(f"{API_URL}/projects/{self.__class__.project_id}")
            
            if response.status_code == 200:
                project = response.json()
                status = project.get("status")
                print(f"Project status (attempt {attempt}/{max_attempts}): {status}")
                
                if status == "completed":
                    project_completed = True
                    print("Project processing completed successfully")
                    break
                elif status == "error":
                    self.fail(f"Project processing failed with error: {project.get('error_message')}")
            else:
                print(f"Failed to get project status: {response.status_code}")
            
            # Wait before next attempt
            time.sleep(2)
        
        self.assertTrue(project_completed, "Project did not complete processing in the allowed time")
    
    def test_05_get_project(self):
        """Test getting a specific project"""
        if not hasattr(self.__class__, 'project_id') or not self.__class__.project_id:
            self.skipTest("No project ID available from upload test")
        
        print(f"\n--- Testing Get Project {self.__class__.project_id} ---")
        response = requests.get(f"{API_URL}/projects/{self.__class__.project_id}")
        print(f"Get project response: {response.status_code}")
        
        self.assertEqual(response.status_code, 200)
        project = response.json()
        self.assertEqual(project["id"], self.__class__.project_id)
        self.assertEqual(project["project_name"], self.project_name)
        
        # Check if project has aligned segments
        self.assertIn("aligned_segments", project)
        if project["aligned_segments"]:
            print(f"Project has {len(project['aligned_segments'])} aligned segments")
            # Print details of the first segment
            print(f"Sample segment: {project['aligned_segments'][0]}")
    
    def test_06_correct_timing(self):
        """Test timing correction functionality"""
        if not hasattr(self.__class__, 'project_id') or not self.__class__.project_id:
            self.skipTest("No project ID available from upload test")
        
        print(f"\n--- Testing Timing Correction for Project {self.__class__.project_id} ---")
        
        # First get the project to find a segment to correct
        response = requests.get(f"{API_URL}/projects/{self.__class__.project_id}")
        if response.status_code != 200 or "aligned_segments" not in response.json():
            self.skipTest("Project not available or doesn't have aligned segments")
        
        project = response.json()
        if not project["aligned_segments"] or not project["aligned_segments"][0].get("words"):
            self.skipTest("Project doesn't have any words to correct")
        
        # Get the first word of the first segment
        segment_index = 0
        word_index = 0
        original_word = project["aligned_segments"][segment_index]["words"][word_index]
        
        # Create a correction with slightly modified timing
        correction = {
            "segment_index": segment_index,
            "word_index": word_index,
            "new_start_time": original_word["start"] + 0.1,
            "new_end_time": original_word["end"] + 0.1
        }
        
        # Send the correction
        response = requests.post(
            f"{API_URL}/projects/{self.__class__.project_id}/correct",
            json=[correction]
        )
        print(f"Correction response: {response.status_code} - {response.text}")
        
        self.assertEqual(response.status_code, 200)
        self.assertIn("message", response.json())
        
        # Verify the correction was applied
        response = requests.get(f"{API_URL}/projects/{self.__class__.project_id}")
        updated_project = response.json()
        updated_word = updated_project["aligned_segments"][segment_index]["words"][word_index]
        
        print(f"Original timing: start={original_word['start']}, end={original_word['end']}")
        print(f"Updated timing: start={updated_word['start']}, end={updated_word['end']}")
        
        self.assertAlmostEqual(updated_word["start"], correction["new_start_time"], places=1)
        self.assertAlmostEqual(updated_word["end"], correction["new_end_time"], places=1)
    
    def test_07_download_ttml(self):
        """Test downloading TTML file"""
        if not hasattr(self.__class__, 'project_id') or not self.__class__.project_id:
            self.skipTest("No project ID available from upload test")
        
        print(f"\n--- Testing TTML Download for Project {self.__class__.project_id} ---")
        response = requests.get(f"{API_URL}/projects/{self.__class__.project_id}/download/ttml")
        
        print(f"TTML download response: {response.status_code}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/xml", response.headers.get("Content-Type", ""))
        
        # Check if the response contains TTML content
        content = response.content.decode("utf-8")
        self.assertIn("<tt", content)
        self.assertIn("xmlns", content)
        print(f"TTML file size: {len(content)} bytes")
    
    def test_08_download_lrc(self):
        """Test downloading LRC file"""
        if not hasattr(self.__class__, 'project_id') or not self.__class__.project_id:
            self.skipTest("No project ID available from upload test")
        
        print(f"\n--- Testing LRC Download for Project {self.__class__.project_id} ---")
        response = requests.get(f"{API_URL}/projects/{self.__class__.project_id}/download/lrc")
        
        print(f"LRC download response: {response.status_code}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response.headers.get("Content-Type", ""))
        
        # Check if the response contains LRC content
        content = response.content.decode("utf-8")
        self.assertIn("[ti:", content)
        self.assertIn("[ar:", content)
        print(f"LRC file size: {len(content)} bytes")

if __name__ == "__main__":
    unittest.main(verbosity=2)