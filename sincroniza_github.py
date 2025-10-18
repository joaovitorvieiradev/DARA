import sys
import traceback

def sync_modulo(nome, modulo_main):
    print(f"\n==== [SYNC] {nome.upper()} ====")
    try:
        modulo_main.main()
        print(f"[OK] Sincronização '{nome}' concluída!")
    except Exception as e:
        print(f"[ERRO] Falha ao sincronizar '{nome}': {e}")
        print(traceback.format_exc())

def main():
    # Sincroniza Operacoes
    try:
        from operacoes import main as main_operacoes
        sync_modulo("operacoes", main_operacoes)
    except Exception as e:
        print(f"[ERRO] Não foi possível importar 'operacoes.main': {e}")
        print(traceback.format_exc())

    # Sincroniza TCF
    try:
        from tcf import main as main_tcf
        sync_modulo("tcf", main_tcf)
    except Exception as e:
        print(f"[ERRO] Não foi possível importar 'tcf.main': {e}")
        print(traceback.format_exc())

    print("\n✅ [SYNC] Sincronização de todos os domínios finalizada!\n")

if __name__ == "__main__":
    main()
