import asyncio
import typer
from rich import print
from .scraper import RemajuScraper

app = typer.Typer(
    help="CLI de gestión y ejecución para el plugin autónomo Chaskitambo Remaju.",
    add_completion=False
)

@app.command("run")
def run_remaju_plugin(
    creds: str = typer.Option("autenticacion.json", "--creds", "-c", help="Ruta al archivo JSON de credenciales."),
    history: str = typer.Option("historial_procesados.json", "--history", "-H", help="Ruta al archivo de historial de procesados."),
    config: str = typer.Option("config.json", "--config", "-f", help="Ruta al archivo de configuración general.")
):
    """
    Ejecuta el raspador REMAJU de manera autónoma y procesa los documentos encontrados.
    """
    print("[bold cyan]🚀 Iniciando ejecución independiente del plugin REMAJU...[/bold cyan]")
    
    async def _ejecutar_scraping():
        scraper = RemajuScraper(
            creds_path=creds,
            history_path=history,
            config_path=config
        )
        
        contador = 0
        async for doc in scraper.extract():
            contador += 1
            print(f"[green]✅ [Documento #{contador}] ID: {doc.id_externo} | Archivo: {doc.nombre_archivo_sugerido}[/green]")
        
        print(f"[bold green]✨ Proceso de extracción finalizado. Total de documentos emitidos: {contador}[/bold green]")

    try:
        asyncio.run(_ejecutar_scraping())
    except KeyboardInterrupt:
        print("[bold yellow]⚠️ Ejecución interrumpida manualmente por el usuario.[/bold yellow]")
    except Exception as e:
        print(f"[bold red]❌ Error crítico en la ejecución del CLI: {e}[/bold red]")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()