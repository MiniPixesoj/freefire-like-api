
from flask import Blueprint, request, jsonify
import asyncio
from datetime import datetime, timezone
import logging
import aiohttp 
import requests
from typing import List


from .utils.protobuf_utils import encode_uid, decode_info, create_protobuf 
from .utils.crypto_utils import encrypt_aes
from .token_manager import get_headers 

logger = logging.getLogger(__name__)

like_bp = Blueprint('like_bp', __name__)


_SERVERS = {}
_token_cache = None


async def async_post_request(url: str, data: bytes, token: str):
    try:
        headers = get_headers(token)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data, headers=headers, timeout=10) as resp:
                return await resp.read()
    except Exception as e:
        logger.error(f"Async request failed: {str(e)}")
        return None

def make_request(uid_enc: str, url: str, token: str):
    data = bytes.fromhex(uid_enc)
    headers = get_headers(token)
    try:
        response = requests.post(url, headers=headers, data=data, timeout=10)
        if response.status_code == 200:
            return decode_info(response.content)
        logger.warning(f"Request failed with status {response.status_code}")
        return None
    except Exception as e:
        logger.error(f"Request error: {str(e)}")
        return None

async def detect_player_region(uid: str, region: str = None):
    logger.info(f"🔍 Intentando detectar región para UID: {uid} (región proporcionada: {region})")

    if not region:
        logger.info("⚠️ Región no especificada.")
        return None, None

    server_url = _SERVERS.get(region.upper())
    if not server_url:
        logger.info(f"❌ Región no válida o no configurada: {region}")
        return None, None

    info_url = f"{server_url}/GetPlayerPersonalShow"
    payload = bytes.fromhex(encode_uid(uid))
    auth_token = "eyJhbGciOiJIUzI1NiIsInN2ciI6IjIiLCJ0eXAiOiJKV1QifQ.eyJhY2NvdW50X2lkIjoxMjYzNjMxMzU1Miwibmlja25hbWUiOiJOb3ZlbDJFNnU2Iiwibm90aV9yZWdpb24iOiJVUyIsImxvY2tfcmVnaW9uIjoiVVMiLCJleHRlcm5hbF9pZCI6IjVhOGIzODE0OTYwZGM0ZWRjODU4YmE4OTAwMWJiNTYzIiwiZXh0ZXJuYWxfdHlwZSI6NCwicGxhdF9pZCI6MSwiY2xpZW50X3ZlcnNpb24iOiIxLjEwOC4zIiwiZW11bGF0b3Jfc2NvcmUiOjEwMCwiaXNfZW11bGF0b3IiOnRydWUsImNvdW50cnlfY29kZSI6Ik5MIiwiZXh0ZXJuYWxfdWlkIjo0MDM4MjY2NjQ1LCJyZWdfYXZhdGFyIjoxMDIwMDAwMDcsInNvdXJjZSI6NCwibG9ja19yZWdpb25fdGltZSI6MTc1MjI5NDQyMSwiY2xpZW50X3R5cGUiOjIsInNpZ25hdHVyZV9tZDUiOiIiLCJ1c2luZ192ZXJzaW9uIjoxLCJyZWxlYXNlX2NoYW5uZWwiOiIzcmRfcGFydHkiLCJyZWxlYXNlX3ZlcnNpb24iOiJPQjQ5IiwiZXhwIjoxNzUyNDQzNjE4fQ.iJp_dOJEWEKcplSlFmRbs0qsNFnwAXqkcg5XszAbtqg"

    logger.info(f"🌐 URL: {info_url}")
    logger.info(f"🧾 Payload HEX: {payload.hex()}")
    logger.info(f"🔑 Token: {auth_token[:50]}...")

    try:
        response = await async_post_request(info_url, payload, auth_token)

        if response:
            status_code = getattr(response, 'status', '???')
            raw_bytes = getattr(response, 'body', response)  # fallback si ya es bytes

            logger.debug(f"✅ Respuesta recibida de {region.upper()} para UID {uid}")
            logger.debug(f"📟 Código de respuesta: {status_code}")
            logger.debug(f"🧱 Bytes recibidos: {len(raw_bytes)}")
            logger.debug(f"🔍 Hex parcial (256): {raw_bytes[:256].hex()}")

            try:
                player_info = decode_info(response)
                if player_info and player_info.AccountInfo.PlayerNickname:
                    logger.info(f"🟢 Jugador encontrado en región {region.upper()}: {player_info.AccountInfo.PlayerNickname}")
                    return region.upper(), player_info
                else:
                    logger.info(f"⚠️ No se encontró información válida del jugador para UID {uid} en región {region}")
            except Exception as decode_error:
                logger.info(f"❌ Error al decodificar Protobuf: {decode_error}")
        else:
            logger.info(f"⚠️ Respuesta vacía o nula desde {region.upper()} para UID {uid}")
    except Exception as e:
        logger.info(f"❌ Excepción al hacer solicitud para UID {uid} en región {region.upper()}: {e}")

    return None, None
        
@like_bp.route("/like", methods=["GET"])
async def like_player():
    try:
        uid = request.args.get("uid")
        region = request.args.get("region")
        amount = request.args.get("amount")
        target_likes = int(amount) if amount and amount.isdigit() else None
        if not uid or not uid.isdigit():
            return jsonify({
                "status": 400,
                "error": "Invalid UID",
                "message": "Valid numeric UID required"
            })

        region, player_info = await detect_player_region(uid, region)
        if not player_info:
            return jsonify({
                "status": 404,
                "error": "Player not found",
                "message": "Player not found on any server",
                "test": player_info
            })

        before_likes = player_info.AccountInfo.Likes
        player_name = player_info.AccountInfo.PlayerNickname
        info_url = f"{_SERVERS[region]}/GetPlayerPersonalShow" 

        #await send_likes(uid, region, target_likes)

        new_info = make_request(encode_uid(uid), info_url, current_tokens[0])
        after_likes = new_info.AccountInfo.Likes if new_info else before_likes

        return jsonify({
            "status": 1 if after_likes > before_likes else 2,
            "uid": uid,
            "player": player_name,
            "likes_added": after_likes - before_likes,
            "likes_before": before_likes,
            "likes_after": after_likes,
            "server_used": region
        })

    except Exception as e:
        logger.error(f"Like error for UID {uid}: {str(e)}", exc_info=True)
        return jsonify({
            "status": 500,
            "error": "Internal server error",
            "message": str(e),
        })

@like_bp.route("/health-check", methods=["GET"])
def health_check():
    try:
        token_status = {
            server: len(_token_cache.get_tokens(server)) > 0 
            for server in _SERVERS 
        }

        return jsonify({
            "status": "healthy" if all(token_status.values()) else "degraded",
            "servers": token_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
        })

@like_bp.route("/", methods=["GET"]) 
async def root_home():
    """
    Route pour la page d'accueil principale de l'API (accessible via '/').
    """
    return jsonify({
        "message": "Api free fire like ",
    })

def initialize_routes(app_instance, servers_config, token_cache_instance):
    global _SERVERS, _token_cache 
    _SERVERS = servers_config
    _token_cache = token_cache_instance
    app_instance.register_blueprint(like_bp)

@like_bp.route("/get-token", methods=["GET"])
def get_first_token():
    region = request.args.get("region")
    if not region:
        return jsonify({
            "status": 400,
            "error": "Missing region parameter"
        })

    token = _token_cache.get_one_token(region.upper())
    if not token:
        return jsonify({
            "status": 404,
            "error": "No tokens available for the specified region"
        })

    return jsonify({
        "status": 1,
        "region": region.upper(),
        "token": token
    })

@like_bp.route("/get-tokens", methods=["GET"])
def get_all_tokens():
    region = request.args.get("region")
    if not region:
        return jsonify({
            "status": 400,
            "error": "Missing region parameter"
        })

    tokens = _token_cache.get_tokens(region.upper())
    if not tokens:
        return jsonify({
            "status": 404,
            "error": "No tokens available for the specified region"
        })

    return jsonify({
        "status": 1,
        "region": region.upper(),
        "tokens": tokens,
        "count": len(tokens)
    })

@like_bp.route("/delete-tokens", methods=["GET"])
def delete_tokens():
    region = request.args.get("region")
    if not region:
        return jsonify({
            "status": 400,
            "error": "Missing region parameter"
        })

    try:
        import redis
        import os

        redis_url = "rediss://default:AV06AAIjcDFkNzE5MTUxNzM0ZTM0YmQ1OTIyN2M0ZjU5ZjBiNzVhZXAxMA@quick-doe-23866.upstash.io:6379"
        redis_client = redis.Redis.from_url(redis_url, decode_responses=True)

        pattern = f"tokens:{region.upper()}:*"
        keys = redis_client.keys(pattern)

        if not keys:
            return jsonify({
                "status": 404,
                "error": "No tokens found for region",
                "region": region.upper()
            })

        deleted_count = redis_client.delete(*keys)

        return jsonify({
            "status": 1,
            "region": region.upper(),
            "deleted_keys": deleted_count
        })

    except Exception as e:
        logger.error(f"Error deleting tokens for {region}: {str(e)}", exc_info=True)
        return jsonify({
            "status": 500,
            "error": "Internal server error",
            "message": str(e)
        })
