import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import dashscope

load_dotenv(Path(__file__).resolve().parents[1] / 'backend' / '.env')
response = dashscope.TextReRank.call(model=sys.argv[1] if len(sys.argv) > 1 else 'gte-rerank', top_n=2, query='test number',
    documents=['Test number is 73.', 'This is unrelated.'], api_key=os.environ['DASHSCOPE_API_KEY'])
print(json.dumps({'status_code': response.status_code, 'code': response.code,
                  'message': response.message, 'output_type': type(response.output).__name__,
                  'output_keys': list(response.output.keys()) if isinstance(response.output, dict) else None,
                  'response_keys': list(response.keys())}, ensure_ascii=False))
