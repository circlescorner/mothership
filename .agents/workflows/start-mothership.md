---
description: Setup and Start the Mothership Application
---
This workflow installs the required Python dependencies and starts the Mothership FastAPI backend.

// turbo-all
1. Install dependencies
`py -m pip install -r requirements.txt`

2. Start the Backend API Server
`py -m uvicorn main:app --port 8000 --reload`
