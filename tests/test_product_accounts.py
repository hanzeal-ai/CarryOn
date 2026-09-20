import time
from test_onboarding import BindingTests


class ProductAccountTests(BindingTests):
    def test_password_change_revokes_only_account_sessions_and_login_codes(self):
        alice = self.register_user('alice')
        bob = self.register_user('bob')
        self.assertEqual(self.request('password',{'currentPassword':'wrong','password':'new password long 123'},alice)[0],403)
        status, _, _ = self.request('password',{'currentPassword':'a long password 123','password':'new password long 123'},alice)
        self.assertEqual(status,200)
        self.assertEqual(self.request('session',cookie=alice)[0],401)
        self.assertEqual(self.request('session',cookie=bob)[0],200)
        self.assertEqual(self.request('login',{'username':'alice','password':'a long password 123'})[0],403)
        self.assertEqual(self.request('login',{'username':'alice','password':'new password long 123'})[0],200)

    def test_target_rejection_and_expiry_never_authorize(self):
        alice=self.register_user('alice')
        invite=self.server.binding_invites.start({'name':'Mac','permissions':['view'],'targetAccount':'alice'})
        self.assertEqual(self.request('binding/respond',{'id':invite['id'],'reject':True},alice)[0],200)
        self.assertEqual(self.request('binding/respond',{'id':invite['id']},alice)[0],403)
        expired=self.server.binding_invites.start({'name':'Mac','permissions':['view'],'targetAccount':'alice'})
        self.server.binding_invites.entries[expired['id']]['expires']=time.time()-1
        self.assertEqual(self.request('binding/respond',{'id':expired['id']},alice)[0],400)
        self.assertEqual(self.server.config['devices'],{})

    def test_cancelled_target_cannot_be_confirmed_by_stale_phone(self):
        alice = self.register_user('alice')
        invite = self.server.binding_invites.start({'name':'Mac','permissions':['view'],'targetAccount':'alice'})
        self.assertEqual(self.request('binding/cancel', {'id':invite['id'],'secret':invite['secret']}, origin=False)[0], 200)
        self.assertEqual(self.request('binding/respond', {'id':invite['id']}, alice)[0], 400)
        self.assertEqual(self.server.binding_invites.entries[invite['id']]['state'], 'cancelled')
        self.assertEqual(self.server.config['devices'], {})
