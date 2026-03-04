# Spotify Smart Queue

Автоматически создаёт еженедельный плейлист из треков, которые ты слушал давно или не слушал никогда.

## Как работает

1. Читает список треков из `LOUNGE.csv` (экспорт с Exportify)
2. Загружает историю прослушиваний из Last.fm (до 10 000 скробблов)
3. Исключает треки, слушанные в последние 30 дней
4. Сортирует: никогда не слушал → слушал давно
5. Создаёт плейлист "🎵 Smart Queue – Week N" в Spotify

## Деплой на Railway

### 1. Загрузи файлы

Создай новый проект на Railway, подключи GitHub репо с этими файлами.
Положи `LOUNGE.csv` рядом с `app.py`.

### 2. Environment Variables

В Railway → Variables добавь:

| Variable | Value |
|---|---|
| `SPOTIFY_CLIENT_ID` | твой Client ID |
| `SPOTIFY_CLIENT_SECRET` | твой Client Secret |
| `SPOTIFY_REDIRECT_URI` | `https://YOUR-APP.railway.app/callback` |
| `SPOTIFY_USER_ID` | твой Spotify User ID (видно в профиле) |
| `LASTFM_API_KEY` | твой Last.fm API ключ |
| `LASTFM_USERNAME` | твой Last.fm username |
| `EXCLUDE_DAYS` | `30` (треки моложе N дней исключаются) |
| `QUEUE_SIZE` | `200` |
| `LASTFM_PAGES` | `50` (50 × 200 = 10 000 скробблов) |

### 3. Spotify Dashboard

В [developer.spotify.com](https://developer.spotify.com) → твоё приложение → Settings:
- Redirect URIs: добавь `https://YOUR-APP.railway.app/callback`

### 4. Первый запуск (авторизация)

Открой в браузере:
```
https://YOUR-APP.railway.app/callback
```
Это откроет окно авторизации Spotify. После входа токен сохранится.

### 5. Запуск генерации плейлиста

```
https://YOUR-APP.railway.app/run
```

Ответ будет примерно таким:
```json
{
  "status": "✅ Success",
  "playlist_name": "🎵 Smart Queue – Week 10 (2026-03-04)",
  "playlist_url": "https://open.spotify.com/playlist/...",
  "stats": {
    "total_in_playlist": 1263,
    "never_played": 340,
    "played_recently_excluded": 87,
    "eligible": 1176,
    "selected": 200
  }
}
```

### 6. Автозапуск каждую неделю

В n8n (уже настроен на Railway):
- Schedule Trigger: каждый понедельник 8:00
- HTTP Request нода → GET `https://YOUR-APP.railway.app/run`

Готово! Каждую неделю будет появляться новый плейлист.
