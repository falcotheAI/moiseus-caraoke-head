import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import './App.css';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

function App() {
  const [projects, setProjects] = useState([]);
  const [currentProject, setCurrentProject] = useState(null);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [activeTab, setActiveTab] = useState('upload');
  const [audioFile, setAudioFile] = useState(null);
  const [textFile, setTextFile] = useState(null);
  const [projectName, setProjectName] = useState('');
  const [language, setLanguage] = useState('ru');
  const [currentTime, setCurrentTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [editingWord, setEditingWord] = useState(null);
  const [newStartTime, setNewStartTime] = useState('');
  const [newEndTime, setNewEndTime] = useState('');
  
  const audioRef = useRef(null);

  // Load projects on component mount
  useEffect(() => {
    loadProjects();
  }, []);

  // Update audio time
  useEffect(() => {
    const audio = audioRef.current;
    if (audio) {
      const updateTime = () => setCurrentTime(audio.currentTime);
      audio.addEventListener('timeupdate', updateTime);
      return () => audio.removeEventListener('timeupdate', updateTime);
    }
  }, [currentProject]);

  const loadProjects = async () => {
    try {
      const response = await axios.get(`${API}/projects`);
      setProjects(response.data);
    } catch (error) {
      console.error('Error loading projects:', error);
    }
  };

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!audioFile || !textFile || !projectName) {
      alert('Пожалуйста, заполните все поля');
      return;
    }

    setUploading(true);
    const formData = new FormData();
    formData.append('audio_file', audioFile);
    formData.append('text_file', textFile);
    formData.append('project_name', projectName);
    formData.append('language', language);

    try {
      const response = await axios.post(`${API}/upload`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      
      alert('Файлы загружены! Начинается обработка...');
      setProjectName('');
      setAudioFile(null);
      setTextFile(null);
      loadProjects();
      setActiveTab('projects');
    } catch (error) {
      console.error('Error uploading files:', error);
      alert('Ошибка при загрузке файлов');
    } finally {
      setUploading(false);
    }
  };

  const loadProject = async (projectId) => {
    setLoading(true);
    try {
      const response = await axios.get(`${API}/projects/${projectId}`);
      setCurrentProject(response.data);
      setActiveTab('editor');
    } catch (error) {
      console.error('Error loading project:', error);
    } finally {
      setLoading(false);
    }
  };

  const saveCorrection = async () => {
    if (!editingWord || !newStartTime || !newEndTime) return;

    const correction = {
      segment_index: editingWord.segmentIndex,
      word_index: editingWord.wordIndex,
      new_start_time: parseFloat(newStartTime),
      new_end_time: parseFloat(newEndTime)
    };

    try {
      await axios.post(`${API}/projects/${currentProject.id}/correct`, [correction]);
      
      // Update local state
      const updatedProject = { ...currentProject };
      updatedProject.aligned_segments[editingWord.segmentIndex].words[editingWord.wordIndex] = {
        ...updatedProject.aligned_segments[editingWord.segmentIndex].words[editingWord.wordIndex],
        start: parseFloat(newStartTime),
        end: parseFloat(newEndTime)
      };
      
      setCurrentProject(updatedProject);
      setEditingWord(null);
      setNewStartTime('');
      setNewEndTime('');
    } catch (error) {
      console.error('Error saving correction:', error);
    }
  };

  const downloadFile = async (format) => {
    try {
      const response = await axios.get(`${API}/projects/${currentProject.id}/download/${format}`, {
        responseType: 'blob'
      });
      
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `${currentProject.project_name}.${format}`);
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (error) {
      console.error('Error downloading file:', error);
    }
  };

  const formatTime = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(1);
    return `${mins}:${secs.padStart(4, '0')}`;
  };

  const isWordActive = (word) => {
    return currentTime >= word.start && currentTime <= word.end;
  };

  const jumpToTime = (time) => {
    if (audioRef.current) {
      audioRef.current.currentTime = time;
    }
  };

  const togglePlay = () => {
    if (audioRef.current) {
      if (playing) {
        audioRef.current.pause();
      } else {
        audioRef.current.play();
      }
      setPlaying(!playing);
    }
  };

  return (
    <div className="App">
      <nav className="bg-gradient-to-r from-blue-600 to-purple-600 text-white p-4">
        <div className="container mx-auto flex justify-between items-center">
          <h1 className="text-2xl font-bold">🎵 Караоке Субтитры</h1>
          <div className="flex space-x-4">
            <button
              onClick={() => setActiveTab('upload')}
              className={`px-4 py-2 rounded ${activeTab === 'upload' ? 'bg-white text-blue-600' : 'bg-blue-500 hover:bg-blue-400'}`}
            >
              Загрузить
            </button>
            <button
              onClick={() => setActiveTab('projects')}
              className={`px-4 py-2 rounded ${activeTab === 'projects' ? 'bg-white text-blue-600' : 'bg-blue-500 hover:bg-blue-400'}`}
            >
              Проекты
            </button>
            {currentProject && (
              <button
                onClick={() => setActiveTab('editor')}
                className={`px-4 py-2 rounded ${activeTab === 'editor' ? 'bg-white text-blue-600' : 'bg-blue-500 hover:bg-blue-400'}`}
              >
                Редактор
              </button>
            )}
          </div>
        </div>
      </nav>

      <div className="container mx-auto p-6">
        {activeTab === 'upload' && (
          <div className="max-w-md mx-auto bg-white rounded-lg shadow-md p-6">
            <h2 className="text-xl font-bold mb-6 text-center">Загрузить файлы</h2>
            <form onSubmit={handleUpload} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Название проекта
                </label>
                <input
                  type="text"
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  required
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Аудио файл (.wav)
                </label>
                <input
                  type="file"
                  accept=".wav"
                  onChange={(e) => setAudioFile(e.target.files[0])}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  required
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Текст песни (.txt или .docx)
                </label>
                <input
                  type="file"
                  accept=".txt,.docx"
                  onChange={(e) => setTextFile(e.target.files[0])}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  required
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Язык
                </label>
                <select
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="ru">Русский</option>
                  <option value="en">English</option>
                </select>
              </div>
              
              <button
                type="submit"
                disabled={uploading}
                className={`w-full py-2 px-4 rounded-md text-white font-semibold ${
                  uploading 
                    ? 'bg-gray-400 cursor-not-allowed' 
                    : 'bg-blue-600 hover:bg-blue-700'
                }`}
              >
                {uploading ? 'Загрузка...' : 'Загрузить файлы'}
              </button>
            </form>
          </div>
        )}

        {activeTab === 'projects' && (
          <div>
            <h2 className="text-2xl font-bold mb-6">Проекты</h2>
            {projects.length === 0 ? (
              <p className="text-gray-500 text-center">Нет проектов</p>
            ) : (
              <div className="grid gap-4">
                {projects.map((project) => (
                  <div key={project.id} className="bg-white rounded-lg shadow-md p-6">
                    <div className="flex justify-between items-start">
                      <div>
                        <h3 className="text-lg font-semibold">{project.project_name}</h3>
                        <p className="text-gray-600">{project.audio_filename}</p>
                        <p className="text-gray-600">{project.text_filename}</p>
                        <p className="text-sm text-gray-500">
                          {new Date(project.created_at).toLocaleDateString()}
                        </p>
                      </div>
                      <div className="flex items-center space-x-2">
                        <span className={`px-2 py-1 rounded-full text-xs ${
                          project.status === 'completed' 
                            ? 'bg-green-100 text-green-800'
                            : project.status === 'processing'
                            ? 'bg-yellow-100 text-yellow-800'
                            : 'bg-red-100 text-red-800'
                        }`}>
                          {project.status === 'completed' ? 'Готово' : 
                           project.status === 'processing' ? 'Обработка' : 'Ошибка'}
                        </span>
                        {project.status === 'completed' && (
                          <button
                            onClick={() => loadProject(project.id)}
                            className="bg-blue-600 text-white px-3 py-1 rounded hover:bg-blue-700"
                          >
                            Открыть
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'editor' && currentProject && (
          <div>
            <div className="bg-white rounded-lg shadow-md p-6 mb-6">
              <h2 className="text-2xl font-bold mb-4">{currentProject.project_name}</h2>
              
              {/* Audio Player */}
              <div className="mb-6">
                <audio
                  ref={audioRef}
                  controls
                  className="w-full"
                  onPlay={() => setPlaying(true)}
                  onPause={() => setPlaying(false)}
                >
                  <source src={`${API}/projects/${currentProject.id}/audio`} type="audio/wav" />
                  Ваш браузер не поддерживает аудио элемент.
                </audio>
              </div>

              {/* Download Buttons */}
              <div className="flex space-x-4 mb-6">
                <button
                  onClick={() => downloadFile('ttml')}
                  className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700"
                >
                  Скачать TTML
                </button>
                <button
                  onClick={() => downloadFile('lrc')}
                  className="bg-purple-600 text-white px-4 py-2 rounded hover:bg-purple-700"
                >
                  Скачать LRC
                </button>
              </div>

              {/* Lyrics with Timing */}
              <div className="space-y-4">
                <h3 className="text-lg font-semibold">Текст с тайминами</h3>
                {currentProject.aligned_segments?.map((segment, segIndex) => (
                  <div key={segIndex} className="border rounded-lg p-4">
                    <div className="text-sm text-gray-600 mb-2">
                      {formatTime(segment.start)} - {formatTime(segment.end)}
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {segment.words?.map((word, wordIndex) => (
                        <span
                          key={wordIndex}
                          className={`px-2 py-1 rounded cursor-pointer transition-colors ${
                            isWordActive(word)
                              ? 'bg-blue-500 text-white'
                              : 'bg-gray-100 hover:bg-gray-200'
                          }`}
                          onClick={() => jumpToTime(word.start)}
                          onDoubleClick={() => {
                            setEditingWord({ segmentIndex: segIndex, wordIndex });
                            setNewStartTime(word.start.toString());
                            setNewEndTime(word.end.toString());
                          }}
                        >
                          {word.word}
                          <span className="text-xs ml-1 opacity-75">
                            {formatTime(word.start)}
                          </span>
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Edit Word Modal */}
            {editingWord && (
              <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
                <div className="bg-white rounded-lg p-6 max-w-md w-full">
                  <h3 className="text-lg font-semibold mb-4">Редактировать тайминг</h3>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">
                        Начальное время (сек)
                      </label>
                      <input
                        type="number"
                        step="0.1"
                        value={newStartTime}
                        onChange={(e) => setNewStartTime(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">
                        Конечное время (сек)
                      </label>
                      <input
                        type="number"
                        step="0.1"
                        value={newEndTime}
                        onChange={(e) => setNewEndTime(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                    <div className="flex space-x-2">
                      <button
                        onClick={saveCorrection}
                        className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700"
                      >
                        Сохранить
                      </button>
                      <button
                        onClick={() => setEditingWord(null)}
                        className="bg-gray-600 text-white px-4 py-2 rounded hover:bg-gray-700"
                      >
                        Отмена
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default App;