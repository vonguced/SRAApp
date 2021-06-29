"""Main module for SRA-App.

In here the logger is defined (default: warning).

For the app to work properly the following options
need to be set accordingly from command line:
- name of neo4j user
- password of the neo4j database
- An email adress is needed to post process the sra data with the
  Entrez tool of NCBI
- host location ot the neo4j db (dafault: 'bolt://localhost:7687')

Set this value in main.py source file:
- location where the bin directory of the neo4j application
  is places (path will get extended by bin! e.g. path/bin/neo4j-admin)"""

from PyQt5.QtWidgets import QApplication
from gui.app import Ui
import sys, argparse
import logging
from os import path
from Bio import Entrez

#SET YOUR PATH to NEO4J
# typical linux path
#neo4j_home = ("/home/USERNAME/.local/share/neo4j-relate/dbmss/dbms-UNIQUE-DBMS-CODE/")
# typical darwin (mac os) path
#neo4j_home = ("/Users/USERNAME/Library/Application\ Support/Neo4j Desktop/Application/relate-data/dbmss/dbms-UNIQUE-DBMS-CODE/")

neo4j_home = path.join(neo4j_home, '')
logger_name = "SRA_App"

def main(host, neo_user, neo_pass, neo4j_home, entrez):
  '''Main Function to start SRA-App'''
  app = QApplication(sys.argv)
  window = Ui(host, neo_user, neo_pass, neo4j_home, entrez,
              parent_logger_name=logger_name)
  sys.exit(app.exec_())

def main_debug():
  Entrez.email = 'SET YOUR EMAIL'
  return("bolt://localhost:7687",
        'NEO4JUSER',
        'NEO4JPASSWORD',
        neo4j_home,
        Entrez)

def args():
  '''Function to grab command line arguments'''
  parser = argparse.ArgumentParser(description="SRA_App - Cédric von Gunten - "
                                               "Master's Thesis - ZHAW 2021")
  parser.add_argument("user", help="neo4j db user") 
  parser.add_argument("password", help="neo4j db password") 
  parser.add_argument("email", help="Entrez (NCBI) email")
  parser.add_argument("-ho", "--host", help="neo4j host adress")
  parser.add_argument("-l", "--log", help="log level")
  args = parser.parse_args()
  if not args.user:
    raise ValueError("User not set!")
  neo_user = args.user
  if not args.password:
    raise ValueError("Password not set!")
  neo_pass = args.password
  if not args.email:
    raise ValueError("Entrez (NCBI) email not set!")
  Entrez.email = args.email
  if not args.host:
    host = "bolt://localhost:7687"
  else:
    host = args.host
  logger = setup_logger()
  if not args.log:
    logger.setLevel(logging.WARNING)
  else:
    numeric_level = getattr(logging, args.log.upper(), None)
    if not isinstance(numeric_level, int):
      raise ValueError('Invalid log level: %s' % args.log)
    logger.setLevel(args.log)
  return {'host':host, 'neo_user':neo_user, 'neo_pass':neo_pass,
          'neo4j_home':neo4j_home, 'entrez':Entrez}

def setup_logger():
  '''Function to set up logger config'''
  logger = logging.getLogger(logger_name)
  fh = logging.FileHandler('sra_app.log', 'w', 'utf-8')
  sh = logging.StreamHandler()
  formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - "
                                "%(message)s")
  fh.setFormatter(formatter)
  sh.setFormatter(formatter)
  logger.addHandler(fh)
  logger.addHandler(sh)
  return logger

app = QApplication(sys.argv)
window = Ui(*main_debug())
