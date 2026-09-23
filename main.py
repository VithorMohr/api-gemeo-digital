import uvicorn
import pandas as pd
import pm4py
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from io import StringIO

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
    
    # 1. Extrair os dados brutos enviados pelo n8n
    dados_texto = payload.get("dados_brutos", "")
    
    try:
        # 2. Converter o texto do PCFactory para uma tabela Pandas (DataFrame)
        # Assumindo que os dados vêm separados por tabulações ou espaços
        df = pd.read_csv(StringIO(dados_texto), sep='\t') 
        
        # 3. Mapear as colunas do PCFactory para o padrão PM4Py
        # Ajuste os nomes das colunas de acordo com o seu log exato se necessário
        df = pm4py.format_dataframe(
            df, 
            case_id='lotCode', 
            activity_key='WODETCODE', 
            timestamp_key='RealDtStart'
        )
        
        # 4. Cálculos Matemáticos de Process Mining
        # Descobrir variantes de execução do processo
        variantes = pm4py.get_variants(df)
        numero_variantes = len(variantes)
        
        # Calcular tempo de atravessamento (Throughput Time)
        all_case_durations = pm4py.get_all_case_durations(df)
        tempo_medio_segundos = sum(all_case_durations) / len(all_case_durations) if all_case_durations else 0
        
        return {
            "status": "sucesso",
            "mensagem": "Análise PM4Py concluída!",
            "estatisticas": {
                "total_eventos": len(df),
                "numero_variantes_processo": numero_variantes,
                "tempo_medio_processamento_segundos": round(tempo_medio_segundos, 2)
            }
        }
        
    except Exception as e:
        return {
            "status": "erro",
            "mensagem": f"Erro ao processar dados com PM4Py: {str(e)}"
        }