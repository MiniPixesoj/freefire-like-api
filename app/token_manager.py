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
        self.cache = TTLCache(maxsize=100, ttl=CACHE_DURATION)
        self.last_refresh = {}
        self.lock = threading.Lock()
        self.session = requests.Session()
        self.servers_config = servers_config

    def get_tokens(self, server_key):
        with self.lock:
            now = time.time()

            redis_key = f"tokens:{server_key}"
            cached_tokens = redis_client.get(redis_key)
            if cached_tokens:
                return json.loads(cached_tokens)

            refresh_needed = (
                server_key not in self.cache or
                server_key not in self.last_refresh or
                (now - self.last_refresh.get(server_key, 0)) > TOKEN_REFRESH_THRESHOLD
            )

            if refresh_needed:
                self._refresh_tokens(server_key)
                self.last_refresh[server_key] = now

            return self.cache.get(server_key, [])

    def _refresh_tokens(self, server_key):
    try:
        creds = self._load_credentials(server_key)
        tokens = []

        for user in creds:
            params = {'uid': user['uid'], 'password': user['password']}
            token = None

            for attempt in range(3):  # Hasta 3 intentos
                try:
                    response = self.session.get(AUTH_URL, params=params, timeout=10)
                    if response.status_code == 200:
                        token = response.json().get("token")
                        if token:
                            tokens.append(token)
                            logger.info(f"✅ Token agregado para {user['uid']} (server {server_key}) en intento {attempt + 1}")
                        else:
                            logger.warning(f"⚠️ Respuesta sin token para {user['uid']} (server {server_key})")
                        break  # éxito o respuesta válida, salimos del ciclo
                    else:
                        logger.warning(f"⛔ Falló obtención de token para {user['uid']} (server {server_key}): HTTP {response.status_code}, Body: {response.text}")
                        break  # no sirve seguir intentando si el error es del servidor
                except requests.exceptions.ReadTimeout:
                    logger.warning(f"⏱ Timeout al intentar token para {user['uid']} (server {server_key}), intento {attempt + 1}")
                except Exception as e:
                    logger.error(f"❌ Error en intento {attempt + 1} para {user['uid']} (server {server_key}): {str(e)}")

        if tokens:
            self.cache[server_key] = tokens
            redis_client.setex(f"tokens:{server_key}", CACHE_DURATION, json.dumps(tokens))
            logger.info(f"🔄 Refrescado tokens para {server_key}. Total: {len(tokens)}")
        else:
            self.cache[server_key] = []
            redis_client.setex(f"tokens:{server_key}", CACHE_DURATION, json.dumps([]))
            logger.warning(f"⚠️ No se obtuvieron tokens válidos para {server_key}. Cache vacía.")

    except Exception as e:
        logger.error(f"🔥 Error crítico durante la actualización de tokens para {server_key}: {str(e)}")
        self.cache[server_key] = []
        redis_client.setex(f"tokens:{server_key}", CACHE_DURATION, json.dumps([]))

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
