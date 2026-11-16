"""Start a private local demo. The database persists between runs."""
import os
from server.env import load_env
load_env()
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import argparse
import threading
import webbrowser

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--public-demo',action='store_true',help='使用单独模拟库，仅开放学生和辅导员体验')
    args=parser.parse_args()
    if args.public_demo:
        os.environ['ZHIXUE_PUBLIC_DEMO']='1'
        os.environ['ZHIXUE_DEMO']='1'
    import uvicorn
    if not args.no_browser:
        threading.Timer(8,lambda:webbrowser.open(f'http://127.0.0.1:{args.port}')).start()
    uvicorn.run('server.main:app',host='127.0.0.1',port=args.port)
