import unittest
from datetime import datetime

from ranking_logic import aplicar_wo_automatico_partidas_vencidas


class RankingLogicTests(unittest.TestCase):
    def test_partida_vencida_aplica_wo_automatico_ao_desafiante(self):
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
            {
                "id": "a3",
                "nome": "Terceiro",
                "ranking": "masculino_principal",
                "posicao": 2,
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

        processadas = aplicar_wo_automatico_partidas_vencidas(
            partidas,
            atletas,
            referencia_dt=datetime(2026, 3, 12, 10, 1),
        )

        self.assertEqual(1, len(processadas))
        self.assertEqual("a1", partidas[0]["vencedor"])
        self.assertTrue(partidas[0]["wo"])
        self.assertEqual("finalizada", partidas[0]["status"])
        self.assertEqual("W.O. por prazo expirado", partidas[0]["resultado"])
        self.assertEqual(1, next(a for a in atletas if a["id"] == "a1")["posicao"])
        self.assertEqual(2, next(a for a in atletas if a["id"] == "a2")["posicao"])
        self.assertEqual(3, next(a for a in atletas if a["id"] == "a3")["posicao"])


if __name__ == "__main__":
    unittest.main()
