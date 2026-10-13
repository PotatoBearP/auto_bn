"""Artifact directories; runtime filenames are overwritten on each operation."""
from pathlib import Path
PROJECT=Path(__file__).resolve().parent
ARTIFACTS=PROJECT/'artifacts'
ENCOUNTER=ARTIFACTS/'runtime'/'encounter'
DEPLOYMENT=ARTIFACTS/'runtime'/'deployment'
COMBAT=ARTIFACTS/'runtime'/'combat'
OCR=ARTIFACTS/'runtime'/'ocr'
VALIDATION=ARTIFACTS/'validation'/'skills'
DEBUG=ARTIFACTS/'development'
TEMPLATES=PROJECT/'assets'/'templates'
for directory in (ENCOUNTER,DEPLOYMENT,COMBAT,OCR,VALIDATION,DEBUG,TEMPLATES):
    directory.mkdir(parents=True,exist_ok=True)
