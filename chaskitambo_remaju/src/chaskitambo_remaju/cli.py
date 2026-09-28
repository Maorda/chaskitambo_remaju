import asyncio
import sys
import logging
import typer
from rich import print
from .scraper import RemajuScraper

# Desactivar logs basura de librerías externas si es necesario para mantener limpia la consola Rich
logging.getLogger("playwright").setLevel(logging.WARNING)

app = typer.Typer(
    help="CLI de gestión y ejecución para el plugin autónomo Chaskitambo Remaju.",
    add_completion=False
)

@app.command("run")
def run_remaju_plugin(
    # CORREGIDO: Se removió la opción '--creds' dado que las credenciales ahora viajan en el archivo .env
    history: str = typer.Option("historial_procesados.json", "--history", "-H", help="Ruta al archivo de historial de procesados."),
    config: str = typer.Option("config.json", "--config", "-f", help="Ruta al archivo de configuración general.")
):
    """
    Ejecuta el raspador REMAJU de manera autónoma y procesa los documentos encontrados.
    """
    print("[bold cyan]🚀 Iniciando ejecución independiente del plugin REMAJU...[/bold cyan]")
    print("[dim white]ℹ️  Nota: Asegúrate de tener configurado tu archivo .env en D:\\libs\\chaskitambo[/dim white]\n")
    
    async def _ejecutar_scraping():
        # CORREGIDO: Instanciación limpia sin 'creds_path' para encajar con el constructor auditado de RemajuScraper
        scraper = RemajuScraper(
            history_path=history,
            config_path=config
        )
        
        contador = 0
        try:
            async for doc in scraper.extract():
                contador += 1
                print(f"[green]✅ [Documento #{contador}] ID: {doc.id_externo} | Archivo: {doc.nombre_archivo_sugerido}[/green]")
        except Exception as e:
            print(f"[bold red]❌ Ocurrió un error intermedio durante la extracción: {e}[/bold red]")
            raise
        
        print(f"\n[bold green]✨ Proceso de extracción finalizado. Total de documentos emitidos: {contador}[/bold green]")

    # OPTIMIZACIÓN: Forzar ProactorEventLoop en Windows para evitar "Event loop is closed" con Playwright
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    try:
        asyncio.run(_ejecutar_scraping())
    except KeyboardInterrupt:
        print("\n[bold yellow]⚠️ Ejecución interrumpida manualmente por el usuario. Limpiando procesos...[/bold yellow]")
    except Exception as e:
        print(f"[bold red]❌ Error crítico en la ejecución del CLI: {e}[/bold red]")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
