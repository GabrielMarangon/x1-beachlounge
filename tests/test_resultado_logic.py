import unittest

from resultado_logic import reverter_resultado_com_snapshot


class ResultadoLogicTests(unittest.TestCase):
    def test_reverter_wo_automatico_restaura_ranking_e_desconsidera_partida(self):
        atletas = [
            {
                "id": "a1",
                "nome": "Desafiante",
                "ranking": "masculino_principal",
                "posicao": 1,
                "wo_consecutivos": 0,
                "ultimo_jogo": "2026-03-22",
                "ultimo_desafio": "2026-03-12",
                "bloqueado_ate": "2026-03-23T12:00",
                "observacoes": "",
            },
            {
                "id": "a2",
                "nome": "Desafiado",
                "ranking": "masculino_principal",
                "posicao": 2,
                "wo_consecutivos": 1,
                "ultimo_jogo": "2026-03-22",
                "ultimo_desafio": "2026-03-12",
                "bloqueado_ate": None,
                "observacoes": "WO",
            },
        ]
        partida = {
            "id": "p1",
            "categoria": "masculino_principal",
            "status": "finalizada",
            "status_antes_resultado": "marcada",
            "resultado": "W.O. por prazo expirado",
            "vencedor": "a1",
            "wo": True,
            "snapshot_pre_resultado": {
                "a1": {
                    "posicao": 2,
                    "wo_consecutivos": 0,
                    "ultimo_jogo": None,
                    "ultimo_desafio": None,
                    "bloqueado_ate": None,
                    "observacoes": "",
                },
                "a2": {
                    "posicao": 1,
                    "wo_consecutivos": 0,
                    "ultimo_jogo": None,
                    "ultimo_desafio": None,
                    "bloqueado_ate": None,
                    "observacoes": "",
                },
            },
        }

        ok, mensagem = reverter_resultado_com_snapshot(partida, atletas)

        self.assertTrue(ok)
        self.assertIn("desconsiderada", mensagem.lower())
        self.assertEqual("desconsiderada", partida["status"])
        self.assertIsNone(partida["resultado"])
        self.assertFalse(partida["wo"])
        self.assertEqual(2, next(a for a in atletas if a["id"] == "a1")["posicao"])
        self.assertEqual(1, next(a for a in atletas if a["id"] == "a2")["posicao"])

    def test_reverter_resultado_manual_retorna_ao_status_anterior(self):
        atletas = [
            {
                "id": "a1",
                "nome": "Atleta 1",
                "ranking": "masculino_principal",
                "posicao": 1,
                "wo_consecutivos": 0,
                "ultimo_jogo": "2026-03-23",
                "ultimo_desafio": None,
                "bloqueado_ate": None,
                "observacoes": "",
            },
            {
                "id": "a2",
                "nome": "Atleta 2",
                "ranking": "masculino_principal",
                "posicao": 2,
                "wo_consecutivos": 0,
                "ultimo_jogo": "2026-03-23",
                "ultimo_desafio": None,
                "bloqueado_ate": None,
                "observacoes": "",
            },
        ]
        partida = {
            "id": "p2",
            "categoria": "masculino_principal",
            "status": "finalizada",
            "status_antes_resultado": "marcada",
            "resultado": "6/4 6/3",
            "vencedor": "a1",
            "wo": False,
            "snapshot_pre_resultado": {
                "a1": {
                    "posicao": 2,
                    "wo_consecutivos": 0,
                    "ultimo_jogo": None,
                    "ultimo_desafio": None,
                    "bloqueado_ate": None,
                    "observacoes": "",
                },
                "a2": {
                    "posicao": 1,
                    "wo_consecutivos": 0,
                    "ultimo_jogo": None,
                    "ultimo_desafio": None,
                    "bloqueado_ate": None,
                    "observacoes": "",
                },
            },
        }

        ok, _ = reverter_resultado_com_snapshot(partida, atletas)

        self.assertTrue(ok)
        self.assertEqual("marcada", partida["status"])
        self.assertIsNone(partida["resultado"])
        self.assertEqual(2, next(a for a in atletas if a["id"] == "a1")["posicao"])
        self.assertEqual(1, next(a for a in atletas if a["id"] == "a2")["posicao"])


if __name__ == "__main__":
    unittest.main()
