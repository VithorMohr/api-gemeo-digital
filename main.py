import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/analisar-fluxo")
async def analisar_processo(request: Request):
    payload = await request.json()
    print("DADOS RECEBIDOS DO N8N:")
    print(payload)

    return {
        "status": "sucesso",
        "mensagem": "Conexão com o motor Python estabelecida via Render!",
        "linhas_recebidas": len(payload)
    }