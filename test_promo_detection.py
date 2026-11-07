import unittest

from promo_detection import detect_and_rank_promos


class PromoDetectionTests(unittest.TestCase):
    def test_detects_and_ranks_promos(self) -> None:
        screenplay = """
        INT. BEDROOM - NIGHT
        MIA
        I can't get this stain out before tonight.
        NARRATOR
        Try BrightWash. Limited time offer — save 30% and buy now for $9.99.

        EXT. STREET - DAY
        TOM
        We should order now, while supplies last.
        """

        promos = detect_and_rank_promos(screenplay)

        self.assertEqual(2, len(promos))
        self.assertGreaterEqual(promos[0].score, promos[1].score)
        self.assertIn("limited time offer", promos[0].segment.lower())

    def test_returns_empty_when_no_promo_cues(self) -> None:
        screenplay = """
        INT. KITCHEN - MORNING
        ANA
        I finally fixed the toaster.
        """

        promos = detect_and_rank_promos(screenplay)
        self.assertEqual([], promos)

    def test_honors_top_k(self) -> None:
        screenplay = """
        SCENE 1
        Buy now.
        SCENE 2
        Buy now with discount.
        """

        promos = detect_and_rank_promos(screenplay, top_k=1)
        self.assertEqual(1, len(promos))


if __name__ == "__main__":
    unittest.main()
