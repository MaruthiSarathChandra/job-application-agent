import unittest

from browser.email_verification import (
    extract_https_links,
    extract_verification_code,
    trusted_verification_link,
)


class EmailVerificationTests(unittest.TestCase):
    def test_extract_code_near_verification_marker(self):
        self.assertEqual(
            extract_verification_code("Your verification code is 483921. It expires soon."),
            "483921",
        )

    def test_extract_fallback_six_digit_code(self):
        self.assertEqual(extract_verification_code("Use 771204 to continue."), "771204")

    def test_extract_links(self):
        links = extract_https_links(
            "Verify at https://careers.example.com/verify?id=123 and continue."
        )
        self.assertEqual(links, ["https://careers.example.com/verify?id=123"])

    def test_same_site_verification_link_is_trusted(self):
        self.assertTrue(
            trusted_verification_link(
                "https://auth.careers.example.com/verify/abc",
                "https://careers.example.com/apply",
            )
        )

    def test_known_ats_family_is_trusted(self):
        self.assertTrue(
            trusted_verification_link(
                "https://candidate.avature.net/verify/abc",
                "https://tenant.avature.net/apply",
            )
        )

    def test_unrelated_domain_is_not_trusted(self):
        self.assertFalse(
            trusted_verification_link(
                "https://unrelated.example/verify/abc",
                "https://careers.example.com/apply",
            )
        )

    def test_explicit_trusted_domain(self):
        self.assertTrue(
            trusted_verification_link(
                "https://verify.mail-company.example/token",
                "https://careers.example.com/apply",
                ["mail-company.example"],
            )
        )


if __name__ == "__main__":
    unittest.main()
