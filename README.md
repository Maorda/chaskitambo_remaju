[build-system]
requires = ["setuptools>=61.0.0"]
build-backend = "setuptools.build_meta"

[project]
name = "chaskitambo-remaju"
version = "0.1.0"
dependencies = [
    "chaskitambo",
    "playwright>=1.40.0" # Herramientas particulares del raspador
]

[project.entry-points."chaskitambo.plugins"]
remaju = "chaskitambo_remaju.scraper:RemajuScraper"