import unittest

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


if __name__ == "__main__":
    unittest.main()
