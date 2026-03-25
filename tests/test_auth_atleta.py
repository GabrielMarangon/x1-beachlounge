from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from app import (
    _backfill_known_athlete_phones,
    _find_athletes_by_identity,
    _normalize_phone,
)


class AthleteAuthTests(unittest.TestCase):
    def test_backfill_known_phone_only_when_missing(self) -> None:
        atletas = [
            {'id': 'a1', 'nome': 'OTAVIO FLORES', 'ranking': 'masculino_principal', 'telefone': ''},
            {'id': 'a2', 'nome': 'ANA POSSEBON', 'ranking': 'feminina_iniciantes'},
        ]

        changed = _backfill_known_athlete_phones(atletas)

        self.assertTrue(changed)
        self.assertEqual(atletas[0]['telefone'], '5599687999')
        self.assertEqual(atletas[1]['telefone'], '5599259193')

    def test_find_athletes_by_identity_returns_all_profiles_for_same_person(self) -> None:
        atletas = [
            {'id': 'm1', 'nome': 'PEDRO CRESPO', 'ranking': 'masculino_principal', 'telefone': '5599557910'},
            {'id': 'i1', 'nome': 'PEDRO CRESPO', 'ranking': 'infantil_a', 'telefone': '(55) 99557-910'},
            {'id': 'x1', 'nome': 'OUTRO NOME', 'ranking': 'masculino_principal', 'telefone': '5599557910'},
        ]

        encontrados = _find_athletes_by_identity('Pedro Crespo', '5599557910', atletas)

        self.assertEqual({item['id'] for item in encontrados}, {'m1', 'i1'})

    def test_phone_normalization_keeps_only_digits(self) -> None:
        self.assertEqual(_normalize_phone('+55 (55) 99637-1821'), '5555996371821')


if __name__ == '__main__':
    unittest.main()
