import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Green API настройки
    GREEN_API_ID_INSTANCE = os.getenv('GREEN_API_ID_INSTANCE')
    GREEN_API_TOKEN_INSTANCE = os.getenv('GREEN_API_TOKEN_INSTANCE')
    GREEN_API_URL = "https://api.green-api.com"
    
    # База данных
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///data/database.db')
    
    # Папки
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'uploads/photos')
    
    # ID группы для отчетов
    GROUP_ID = os.getenv('GROUP_ID', '')
    
    # Другие настройки
    DEBUG = True