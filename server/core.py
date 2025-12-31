from database import *
import socket
import threading
import json
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

class APICore(Database):
    def __init__(self):
        super().__init__()

    def companies_all_list(self):
        status, data = self.cmd("""
            SELECT * FROM companies
            WHERE status = 'active'
        """, action="fetchall")

        return status, data


if __name__ == "__main__":
    api_core = APICore()
    print(api_core.companies_all_list())
