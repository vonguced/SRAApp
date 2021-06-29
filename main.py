# -*- coding: utf-8 -*-
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

from PyQt5.QtWidgets import QApplication, QDesktopWidget
from gui.app import Ui
import sys, argparse
import logging
import platform
from os import path
from Bio import Entrez

#SET YOUR PATH to NEO4J
# typical linux path
#neo4j_home = ("/home/USERNAME/.local/share/neo4j-relate/dbmss/dbms-UNIQUE-DBMS-CODE/")
# typical darwin (mac os) path
#neo4j_home = ("/Users/USERNAME/Library/Application\ Support/Neo4j Desktop/Application/relate-data/dbmss/dbms-UNIQUE-DBMS-CODE/")

if neo4j_home == "":
  raise ValueError("Neo4j Home not set - Please specify in main.py")

neo4j_home = path.join(neo4j_home, '')
logger_name = "SRA_App"

def main(host, neo_user, neo_pass, neo4j_home, entrez,
         raw_db_name='raw', subset_db_name='subset',
         export_type='ncbi'):
  '''Main Function to start SRA-App'''
  app = QApplication(sys.argv)
  window = Ui(host, neo_user, neo_pass, neo4j_home, entrez,
              raw_db_name=raw_db_name, subset_db_name=subset_db_name,
              parent_logger_name=logger_name)
  window.resize(window.sizeHint())
  qtRectangle = window.frameGeometry()
  centerPoint = QDesktopWidget().availableGeometry().center()
  qtRectangle.moveCenter(centerPoint)
  window.move(qtRectangle.topLeft())
  sys.exit(app.exec_())

def args():
  '''Function to grab command line arguments'''
  parser = argparse.ArgumentParser(description="SRAApp - Cédric von Gunten - "
                                               "Master's Thesis - ZHAW 2021")
  parser.add_argument("user", help="Neo4j db user")
  parser.add_argument("password", help="Neo4j db password")
  parser.add_argument("email", help="Entrez (NCBI) email")
  parser.add_argument("-ho", "--host", help="Neo4j host adress (default: bolt://localhost:7687)")
  parser.add_argument("-l", "--log", help="Log level (default: WARNING)")
  parser.add_argument("-r", "--raw", help="Name of raw DB (default: raw)")
  parser.add_argument("-s", "--subset", help="Name of subset DB (default: subset)")
  #parser.add_argument("-ex", "--export", help="Type of export urls (NCBI, AWS, GCP)")
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
  if not args.raw:
    raw = 'raw'
  else:
    raw = args.raw
  if not args.subset:
    subset = 'subset'
  else:
    subset = args.subset
  # if not args.export:
  #   export = 'NCBI'
  # elif not args.export.upper() in ['NCBI', 'AWS', 'GCP']:
  #   raise ValueError('Invalid export type: %s' % args.export)
  # else:
  #   export = args.export
  return {'host':host, 'neo_user':neo_user, 'neo_pass':neo_pass,
          'neo4j_home':neo4j_home, 'entrez':Entrez, 'raw_db_name':raw,
          'subset_db_name':subset}

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

if __name__ == '__main__':
  main(**args())
