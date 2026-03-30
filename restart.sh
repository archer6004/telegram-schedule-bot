#!/bin/bash
# 봇 안전 재시작 스크립트
# 사용법: ./restart.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$SCRIPT_DIR/bot.log"

echo "▶ 기존 봇 프로세스 종료 중..."
PIDS=$(ps aux | grep "main.py" | grep -v grep | awk '{print $2}')
if [ -n "$PIDS" ]; then
    kill $PIDS 2>/dev/null
    echo "  종료된 PID: $PIDS"
else
    echo "  실행 중인 프로세스 없음"
fi

echo "▶ Telegram 폴링 만료 대기 (30초)..."
sleep 30

echo "▶ 봇 시작..."
cd "$SCRIPT_DIR"
nohup python3 main.py >> "$LOG" 2>&1 &
echo "  PID: $! | 로그: $LOG"
