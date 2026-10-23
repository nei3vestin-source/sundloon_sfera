# ProfiStaffChat Discord Bot

## Установка

1. Установить Python 3.10+
2. Установить Redis (на том же сервере, что и Minecraft)
3. `pip install -r requirements.txt`
4. Отредактировать `config.yml`
5. Запустить: `python bot.py`

## Автозапуск (Linux systemd)

Создать `/etc/systemd/system/profistaffchat-bot.service`:

```ini
[Unit]
Description=ProfiStaffChat Discord Bot
After=network.target redis.service

[Service]
Type=simple
User=minecraft
WorkingDirectory=/opt/profistaffchat-bot
ExecStart=/usr/bin/python3 bot.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
