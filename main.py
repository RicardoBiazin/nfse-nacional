"""Ponto de entrada: sem argumentos abre a interface; com argumentos, a linha de comando."""
import sys


def main() -> int:
    if len(sys.argv) > 1:
        from nfse_nacional.cli import main as cli
        return cli()
    from nfse_nacional.interface.janela import executar
    return executar()


if __name__ == "__main__":
    sys.exit(main())
