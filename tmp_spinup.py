import asyncio
import os
import sys
from dotenv import load_dotenv

sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from devplane.infra.kasm import create_workspace

load_dotenv()

async def main():
    print("Spinning up pycharm-kilo workspace...")
    result = await create_workspace("pycharm-kilo", "test@example.com")
    print("Result:", result)

if __name__ == "__main__":
    asyncio.run(main())
