import unittest
from unittest.mock import Mock

from agent import WordPress
from providers import Held


class WordPressAuthErrors(unittest.TestCase):
    def client(self, error):
        wp = WordPress.__new__(WordPress)
        wp.cfg = {'site_url': 'https://mahotels.net'}
        response = Mock(status_code=401, ok=False)
        response.json.return_value = error
        wp.http = Mock()
        wp.http.request.return_value = response
        return wp

    def test_unauthenticated_error_explains_repair_and_header_check(self):
        wp = self.client({'code': 'rest_not_logged_in', 'message': 'private server response must not be logged'})
        with self.assertRaises(Held) as caught:
            wp.call('users/me?context=edit')
        message = str(caught.exception)
        self.assertIn('rest_not_logged_in', message)
        self.assertIn('REPAIR-WORDPRESS.cmd', message)
        self.assertIn('Authorization-header', message)
        self.assertNotIn('private server response', message)

    def test_untrusted_error_code_and_body_are_not_printed(self):
        wp = self.client({'code': 'secret\n<script>bad</script>', 'message': 'sensitive-content'})
        with self.assertRaises(Held) as caught:
            wp.call('users/me?context=edit')
        self.assertNotIn('secret', str(caught.exception))
        self.assertNotIn('sensitive-content', str(caught.exception))
        self.assertIn('WordPress HTTP 401', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
