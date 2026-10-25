"""Start a private local demo. The database persists between runs."""
import os
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import argparse
import threading
import webbrowser

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    import uvicorn
    if not args.no_browser:
        threading.Timer(8,lambda:webbrowser.open(f'http://127.0.0.1:{args.port}')).start()
    uvicorn.run('server.main:app',host='127.0.0.1',port=args.port)
