#!/usr/bin/env bash
set -e

if [ ! -f .env ]; then
  if [ -f .env.template ]; then
    echo "Creating .env from .env.template..."
    cp .env.template .env
    echo "Please set your BOT_TOKEN in .env and run this script again."
    exit 1
  fi
fi

echo "Installing requirements..."
pip install -r requirements.txt

echo "Starting postingpost bot..."
python main.py
