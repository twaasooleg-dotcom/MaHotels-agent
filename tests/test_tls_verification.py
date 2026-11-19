import ssl
import unittest

import agent
import truststore


class CertificateVerificationTests(unittest.TestCase):
    def test_native_trust_keeps_certificate_and_hostname_checks_required(self):
        context = ssl.create_default_context()
        self.assertIsInstance(context, truststore.SSLContext)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)


if __name__ == '__main__':
    unittest.main()
