#!/usr/bin/env bash

# NETRAKSH Final Cleanup Script
# Removes development artifacts, temporary files, and __pycache__ before production deployment.

echo "Starting NETRAKSH final cleanup..."

# 1. Remove Python bytecode
echo "Cleaning Python __pycache__ and .pyc files..."
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -type f -name "*.pyc" -delete
find . -type f -name "*.pyo" -delete

# 2. Remove Node modules (forces a clean install on next build)
# echo "Cleaning node_modules..."
# rm -rf frontend/node_modules
# rm -f frontend/package-lock.json

# 3. Clean temporary SQLite databases if moving fully to Postgres
echo "Removing development SQLite databases..."
find . -type f -name "*.db" ! -path "*/postgres_data/*" -delete
find . -type f -name "*.sqlite" -delete

# 4. Remove temporary script outputs
echo "Removing scratch files..."
rm -f scratch/*
rm -rf logs/*

echo "Cleanup complete! The repository is ready for production handover."
