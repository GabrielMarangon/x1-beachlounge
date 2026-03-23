import unittest
from datetime import datetime

from ranking_logic import aplicar_wo_automatico_partidas_vencidas
from regras_ranking import pode_desafiar_com_partidas


class RegrasRankingTests(unittest.TestCase):
    def test_aguardando_data_bloqueia_novos_desafios(self):
        atletas = [
            {
                "id": "a1",
                "nome": "Atleta 1",
                "ranking": "masculino_principal",
                "posicao": 3,
                "ativo": True,
                "retirado": False,
                "neutro": False,
                "bloqueio_secretaria": False,
                "bloqueio_motivo": "",
                "bloqueado_ate": None,
            },
            {
                "id": "a2",
                "nome": "Atleta 2",
                "ranking": "masculino_principal",
                "posicao": 2,
                "ativo": True,
                "retirado": False,
                "neutro": False,
                "bloqueio_secretaria": False,
                "bloqueio_motivo": "",
                "bloqueado_ate": None,
            },
            {
                "id": "a3",
                "nome": "Atleta 3",
                "ranking": "masculino_principal",
                "posicao": 1,
                "ativo": True,
                "retirado": False,
                "neutro": False,
                "bloqueio_secretaria": False,
                "bloqueio_motivo": "",
                "bloqueado_ate": None,
            },
        ]
        partidas = [
            {
                "id": "p1",
                "desafiante": "a1",
                "desafiado": "a2",
                "status": "aguardando_data",
            }
        ]

        valido, mensagem = pode_desafiar_com_partidas(
            atletas[0],
            atletas[2],
            partidas=partidas,
            atletas=atletas,
        )

        self.assertFalse(valido)
        self.assertIn("Desafiante em desafio", mensagem)

    def test_repeticao_do_mesmo_confronto_fica_bloqueada_apos_wo_automatico(self):
        atletas = [
            {
                "id": "a1",
                "nome": "Desafiante",
                "ranking": "masculino_principal",
                "posicao": 3,
                "ativo": True,
                "retirado": False,
                "neutro": False,
                "bloqueio_secretaria": False,
                "bloqueio_motivo": "",
                "bloqueado_ate": None,
                "ultimo_jogo": None,
                "ultimo_desafio": None,
                "wo_consecutivos": 0,
                "observacoes": "",
            },
            {
                "id": "a2",
                "nome": "Desafiado",
                "ranking": "masculino_principal",
                "posicao": 1,
                "ativo": True,
                "retirado": False,
                "neutro": False,
                "bloqueio_secretaria": False,
                "bloqueio_motivo": "",
                "bloqueado_ate": None,
                "ultimo_jogo": None,
                "ultimo_desafio": None,
                "wo_consecutivos": 0,
                "observacoes": "",
            },
        ]
        partidas = [
            {
                "id": "p001",
                "desafiante": "a1",
                "desafiado": "a2",
                "categoria": "masculino_principal",
                "status": "aguardando_data",
                "resultado": None,
                "vencedor": None,
                "wo": False,
                "data_registro_resultado": None,
                "data_desafio": "2026-03-01T10:00",
                "observacoes": "",
            }
        ]

        aplicar_wo_automatico_partidas_vencidas(
            partidas,
            atletas,
            referencia_dt=datetime(2026, 3, 12, 10, 1),
        )

        desafiante_atual = next(a for a in atletas if a["id"] == "a2")
        desafiado_atual = next(a for a in atletas if a["id"] == "a1")
        valido, mensagem = pode_desafiar_com_partidas(
            desafiante_atual,
            desafiado_atual,
            partidas=partidas,
            atletas=atletas,
            referencia_dt=datetime(2026, 3, 13, 9, 0),
        )

        self.assertFalse(valido)
        self.assertIn("Repetição do mesmo confronto bloqueada", mensagem)
        self.assertIn("23:59", mensagem)

    def test_repeticao_do_mesmo_confronto_expira_so_ao_fim_do_dia(self):
        atletas = [
            {
                "id": "a1",
                "nome": "Atleta 1",
                "ranking": "masculino_principal",
                "posicao": 1,
                "ativo": True,
                "retirado": False,
                "neutro": False,
                "bloqueio_secretaria": False,
                "bloqueio_motivo": "",
                "bloqueado_ate": None,
            },
            {
                "id": "a2",
                "nome": "Atleta 2",
                "ranking": "masculino_principal",
                "posicao": 2,
                "ativo": True,
                "retirado": False,
                "neutro": False,
                "bloqueio_secretaria": False,
                "bloqueio_motivo": "",
                "bloqueado_ate": None,
            },
        ]
        partidas = [
            {
                "id": "p-legado",
                "desafiante": "a1",
                "desafiado": "a2",
                "categoria": "masculino_principal",
                "status": "desconsiderada",
                "resultado": "W.O. por prazo expirado",
                "vencedor": "a1",
                "wo": True,
                "data_registro_resultado": "2026-03-12T10:01",
                "data_desafio": "2026-03-01T09:00",
                "observacoes": "W.O. automático por prazo expirado em favor do desafiante.",
            }
        ]

        valido, mensagem = pode_desafiar_com_partidas(
            atletas[1],
            atletas[0],
            partidas=partidas,
            atletas=atletas,
            referencia_dt=datetime(2026, 3, 22, 18, 0),
        )

        self.assertFalse(valido)
        self.assertIn("23:59", mensagem)

        valido, _ = pode_desafiar_com_partidas(
            atletas[1],
            atletas[0],
            partidas=partidas,
            atletas=atletas,
            referencia_dt=datetime(2026, 3, 23, 0, 0),
        )

        self.assertTrue(valido)

    def test_repeticao_do_mesmo_confronto_fica_bloqueada_para_wo_legado_desconsiderado(self):
        atletas = [
            {
                "id": "a1",
                "nome": "Atleta 1",
                "ranking": "masculino_principal",
                "posicao": 1,
                "ativo": True,
                "retirado": False,
                "neutro": False,
                "bloqueio_secretaria": False,
                "bloqueio_motivo": "",
                "bloqueado_ate": None,
            },
            {
                "id": "a2",
                "nome": "Atleta 2",
                "ranking": "masculino_principal",
                "posicao": 2,
                "ativo": True,
                "retirado": False,
                "neutro": False,
                "bloqueio_secretaria": False,
                "bloqueio_motivo": "",
                "bloqueado_ate": None,
            },
        ]
        partidas = [
            {
                "id": "p-legado",
                "desafiante": "a1",
                "desafiado": "a2",
                "categoria": "masculino_principal",
                "status": "desconsiderada",
                "resultado": "W.O. por prazo expirado",
                "vencedor": "a1",
                "wo": True,
                "data_desafio": "2026-03-10T09:00",
                "observacoes": "W.O. automático por prazo expirado em favor do desafiante.",
            }
        ]

        valido, mensagem = pode_desafiar_com_partidas(
            atletas[1],
            atletas[0],
            partidas=partidas,
            atletas=atletas,
            referencia_dt=datetime(2026, 3, 12, 10, 0),
        )

        self.assertFalse(valido)
        self.assertIn("Repetição do mesmo confronto bloqueada", mensagem)


if __name__ == "__main__":
    unittest.main()
