"""
WSGI entry point for PythonAnywhere deployment.

PythonAnywhere setup:
1. Upload/clone this repo to /home/<username>/PDFReverse
2. Create a web app: Manual Configuration → Python 3.10+
3. In the WSGI config file (/var/www/<username>_pythonanywhere_com_wsgi.py),
   replace ALL contents with:

       import sys
       import os

       project_home = '/home/<username>/PDFReverse'
       if project_home not in sys.path:
           sys.path.insert(0, project_home)

       os.environ['SECRET_KEY'] = 'change-this-to-a-random-string'

       from wsgi import application

4. Set virtualenv path or install deps:
       pip install --user flask pikepdf

5. In the "Static files" section on the Web tab, add:
       URL: /static/    Directory: /home/<username>/PDFReverse/static

6. Click "Reload" → live at https://<username>.pythonanywhere.com
"""

import os
import sys

# Ensure the project directory is in the path
project_dir = os.path.dirname(os.path.abspath(__file__))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

from app import app as application
