from allauth.account.adapter import DefaultAccountAdapter


class AccountAdapter(DefaultAccountAdapter):
    """Accounts are provisioned by administrators via /admin/ — self-service
    signup is disabled."""

    def is_open_for_signup(self, request):
        return False
