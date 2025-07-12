# app/token_manager.py
import os
import json
import threading
import time
import logging
import requests
import redis
from cachetools import TTLCache
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

AUTH_URL = os.getenv("AUTH_URL", "https://jwtxthug.up.railway.app/token") 
CACHE_DURATION = timedelta(hours=7).seconds
TOKEN_REFRESH_THRESHOLD = timedelta(hours=6).seconds

# Configurar Redis (Upstash)
redis_client = redis.Redis.from_url(
    os.getenv("REDIS_URL", "rediss://default:AV06AAIjcDFkNzE5MTUxNzM0ZTM0YmQ1OTIyN2M0ZjU5ZjBiNzVhZXAxMA@quick-doe-23866.upstash.io:6379"),
    decode_responses=True
)

class TokenCache:
    def __init__(self, servers_config):
        self.lock = threading.Lock()
        self.session = requests.Session()
        self.servers_config = servers_config

    
    def get_tokens(self, server_key):
        with self.lock:
            now = time.time()
            creds = self._load_credentials(server_key)
            valid_tokens = []

            def process_user(user):
                uid = user["uid"]
                redis_key = f"tokens:{server_key}:{uid}"
                entry = redis_client.get(redis_key)
                if entry:
                    try:
                        data = json.loads(entry)
                        if now - data.get("timestamp", 0) < CACHE_DURATION:
                            return data["token"]
                    except Exception:
                        pass
                token = self._get_new_token(user)
                if token:
                    redis_client.set(redis_key, json.dumps({
                        "token": token,
                        "timestamp": now
                    }))
                return token

            with ThreadPoolExecutor(max_workers=10) as executor:
                results = executor.map(process_user, creds)

            valid_tokens = [token for token in results if token]
            return valid_tokens

    def _get_new_token(self, user):
        for attempt in range(3):
            try:
                response = self.session.get(AUTH_URL, params={
                    'uid': user['uid'], 'password': user['password']
                }, timeout=10)

                if response.status_code == 200:
                    token = response.json().get("token")
                    if token:
                        logger.info(f"✅ Nuevo token para UID {user['uid']}")
                        return token
                    else:
                        logger.warning(f"⚠️ Token vacío para UID {user['uid']}")
                        break
                else:
                    logger.warning(f"⛔ Error {response.status_code} al obtener token para UID {user['uid']}")
                    break
            except requests.exceptions.ReadTimeout:
                logger.warning(f"⏱ Timeout al obtener token para UID {user['uid']}, intento {attempt+1}")
            except Exception as e:
                logger.error(f"❌ Error al obtener token para UID {user['uid']}: {str(e)}")
        return None

    def _load_credentials(self, server_key):
        try:
            config_data = os.getenv(f"{server_key}_CONFIG")
            if config_data:
                return json.loads(config_data)

            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', f'{server_key.lower()}_config.json')
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    return json.load(f)
            else:
                logger.warning(f"Config file not found for {server_key}: {config_path}. No credentials loaded.")
                return []
        except Exception as e:
            logger.error(f"Error loading credentials for {server_key}: {str(e)}")
            return []

def get_headers(token: str):
    return {
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        'Connection': "Keep-Alive",
        'Accept-Encoding': "gzip",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Unity-Version": "2018.4.11f1",
        "X-GA": "v1 1",
        "ReleaseVersion": "OB49"
    }
