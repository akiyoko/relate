# -*- coding: utf-8 -*-

from __future__ import division

__copyright__ = "Copyright (C) 2014 Andreas Kloeckner"

__license__ = """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

from django.utils.translation import ugettext_lazy as _, string_concat
from django.shortcuts import (  # noqa
        render, get_object_or_404, redirect, resolve_url)
from django.contrib import messages
import django.forms as forms
from django.core.exceptions import (PermissionDenied, SuspiciousOperation,
        ObjectDoesNotExist)
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit
from django.db.models import Q
from django.conf import settings
from django.contrib.auth import (get_user_model, REDIRECT_FIELD_NAME,
        login as auth_login,)
from django.contrib.auth.forms import \
        AuthenticationForm as AuthenticationFormBase
from django.contrib.sites.shortcuts import get_current_site
from django.contrib.auth.decorators import user_passes_test
from django.core.urlresolvers import reverse
from django.core import validators
from django.utils.http import is_safe_url
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect

from course.models import (
        UserStatus, user_status,
        Participation, participation_role, participation_status,
        )

from relate.utils import StyledForm, StyledModelForm
from django_select2.forms import Select2Widget


# {{{ impersonation

def may_impersonate(user):
    return user.is_staff


def whom_may_impersonate(impersonator):
    if impersonator.is_superuser:
        return get_user_model().objects.filter(
                participation__status=participation_status.active)

    my_privileged_participations = Participation.objects.filter(
            user=impersonator,
            status=participation_status.active,
            role__in=(
                participation_role.instructor,
                participation_role.teaching_assistant))

    q_object = None

    for part in my_privileged_participations:
        if part.role == participation_role.instructor:
            impersonable_roles = (
                participation_role.teaching_assistant,
                participation_role.observer,
                participation_role.auditor,
                participation_role.student)
        elif part.role == participation_role.teaching_assistant:
            impersonable_roles = (
                participation_role.student,
                participation_role.auditor,
                )
        else:
            assert False

        part_q_object = Q(
                participation__course=part.course,
                participation__status=participation_status.active,
                participation__role__in=impersonable_roles)

        if q_object is None:
            q_object = part_q_object
        else:
            q_object = q_object | part_q_object

    return set(get_user_model().objects.filter(q_object).order_by("last_name"))


class ImpersonateMiddleware(object):
    def process_request(self, request):
        if request.user.is_staff and 'impersonate_id' in request.session:
            imp_id = request.session['impersonate_id']

            request.relate_impersonate_original_user = request.user
            if imp_id is not None:
                impersonees = whom_may_impersonate(request.user)
                if any(u.id == imp_id for u in impersonees):
                    request.user = get_user_model().objects.get(id=imp_id)
                else:
                    messages.add_message(request, messages.ERROR,
                            _("Error while impersonating."))


class ImpersonateForm(StyledForm):
    def __init__(self, impersonator, *args, **kwargs):
        super(ImpersonateForm, self).__init__(*args, **kwargs)

        impersonees = whom_may_impersonate(impersonator)

        self.fields["user"] = forms.ChoiceField(
                choices=[
                    (
                        # Translators: information displayed when selecting
                        # userfor impersonating. Customize how the name is
                        # shown, but leave email first to retain usability
                        # of form sorted by last name.
                        u.id, _("%(user_email)s - %(user_lastname)s, "
                            "%(user_firstname)s")
                            % {
                                "user_email": u.email,
                                "user_lastname": u.last_name,
                                "user_firstname": u.first_name
                                })
                    for u in sorted(impersonees,
                        key=lambda user: user.last_name.lower())
                    ],
                required=True,
                help_text=_("Select user to impersonate."),
                widget=Select2Widget(),
                label=_("User"))

        self.helper.add_input(Submit("submit", _("Impersonate")))


@user_passes_test(may_impersonate)
def impersonate(request):
    if hasattr(request, "relate_impersonate_original_user"):
        messages.add_message(request, messages.ERROR,
                _("Already impersonating someone."))
        return redirect("relate-stop_impersonating")

    if request.method == 'POST':
        form = ImpersonateForm(request.user, request.POST)
        if form.is_valid():
            user = get_user_model().objects.get(id=form.cleaned_data["user"])

            request.session['impersonate_id'] = user.id

            # Because we'll likely no longer have access to this page.
            return redirect("relate-home")
    else:
        form = ImpersonateForm(request.user)

    return render(request, "generic-form.html", {
        "form_description": _("Impersonate user"),
        "form": form
        })


class StopImpersonatingForm(forms.Form):
    def __init__(self, *args, **kwargs):
        self.helper = FormHelper()
        super(StopImpersonatingForm, self).__init__(*args, **kwargs)

        self.helper.add_input(Submit("submit", _("Stop impersonating")))


def stop_impersonating(request):
    if not hasattr(request, "relate_impersonate_original_user"):
        messages.add_message(request, messages.ERROR,
                _("Not currently impersonating anyone."))
        return redirect("relate-home")

    if request.method == 'POST':
        form = StopImpersonatingForm(request.POST)
        if form.is_valid():
            messages.add_message(request, messages.INFO,
                    _("No longer impersonating anyone."))
            del request.session['impersonate_id']

            # Because otherwise the header will show stale data.
            return redirect("relate-home")
    else:
        form = StopImpersonatingForm()

    return render(request, "generic-form.html", {
        "form_description": _("Stop impersonating user"),
        "form": form
        })


def impersonation_context_processor(request):
    return {
            "currently_impersonating":
            hasattr(request, "relate_impersonate_original_user"),
            }

# }}}


def make_sign_in_key(user):
    # Try to ensure these hashes aren't guessable.
    import random
    import hashlib
    from time import time
    m = hashlib.sha1()
    m.update(user.email)
    m.update(hex(random.getrandbits(128)))
    m.update(str(time()))
    return m.hexdigest()


def check_sign_in_key(user_id, token):
    user = get_user_model().objects.get(id=user_id)
    ustatuses = UserStatus.objects.filter(
            user=user, sign_in_key=token)

    assert ustatuses.count() <= 1
    if ustatuses.count() == 0:
        return False

    return True


class TokenBackend(object):
    def authenticate(self, user_id=None, token=None):
        user = get_user_model().objects.get(id=user_id)
        ustatuses = UserStatus.objects.filter(
                user=user, sign_in_key=token)

        assert ustatuses.count() <= 1
        if ustatuses.count() == 0:
            return None

        (ustatus,) = ustatuses

        ustatus.status = user_status.active
        ustatus.sign_in_key = None
        ustatus.save()

        return ustatus.user

    def get_user(self, user_id):
        try:
            return get_user_model().objects.get(pk=user_id)
        except get_user_model().DoesNotExist:
            return None


# {{{ conventional login

class LoginForm(AuthenticationFormBase):
    def __init__(self, *args, **kwargs):
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.label_class = "col-lg-2"
        self.helper.field_class = "col-lg-8"

        self.helper.add_input(Submit("submit", _("Sign in")))

        super(LoginForm, self).__init__(*args, **kwargs)


@sensitive_post_parameters()
@csrf_protect
@never_cache
def sign_in_by_user_pw(request, redirect_field_name=REDIRECT_FIELD_NAME):
    """
    Displays the login form and handles the login action.
    """
    redirect_to = request.POST.get(redirect_field_name,
                                   request.GET.get(redirect_field_name, ''))

    if request.method == "POST":
        form = LoginForm(request, data=request.POST)
        if form.is_valid():

            # Ensure the user-originating redirection url is safe.
            if not is_safe_url(url=redirect_to, host=request.get_host()):
                redirect_to = resolve_url(settings.LOGIN_REDIRECT_URL)

            user = form.get_user()

            from course.exam import may_sign_in
            if not may_sign_in(request, user):
                messages.add_message(request, messages.ERROR,
                        _("Sign-in not allowed in this facility."))
                raise PermissionDenied(
                        _("user not allowed to sign in in facility"))

            # Okay, security check complete. Log the user in.
            auth_login(request, user)

            return HttpResponseRedirect(redirect_to)
    else:
        form = LoginForm(request)

    current_site = get_current_site(request)

    context = {
        'form': form,
        redirect_field_name: redirect_to,
        'site': current_site,
        'site_name': current_site.name,
    }

    return TemplateResponse(request, "course/login.html", context)


class SignUpForm(StyledModelForm):
    username = forms.CharField(required=True, max_length=30,
            label=_("Username"),
            validators=[
                validators.RegexValidator('^[\\w.@+-]+$',
                    string_concat(
                        _('Enter a valid username.'), (' '),
                        _('This value may contain only letters, '
                          'numbers and @/./+/-/_ characters.')
                        ),
                    'invalid')
                ])

    class Meta:
        model = get_user_model()
        fields = ("email",)

    def __init__(self, *args, **kwargs):
        super(SignUpForm, self).__init__(*args, **kwargs)

        self.fields["email"].required = True

        self.helper.add_input(
                Submit("submit", _("Send email")))


def sign_up(request):
    if settings.STUDENT_SIGN_IN_VIEW != "relate-sign_in_by_user_pw":
        raise SuspiciousOperation(
                _("password-based sign-in is not being used"))

    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            if get_user_model().objects.filter(
                    username=form.cleaned_data["username"]).count():
                messages.add_message(request, messages.ERROR,
                        _("A user with that username already exists."))

            elif get_user_model().objects.filter(
                    email__iexact=form.cleaned_data["email"]).count():
                messages.add_message(request, messages.ERROR,
                        _("That email address is already in use. "
                        "Would you like to "
                        "<a href='%s'>reset your password</a> instead?")
                        % reverse(
                            "relate-reset_password")),
            else:
                email = form.cleaned_data["email"]
                user = get_user_model()(
                        email=email,
                        username=form.cleaned_data["username"])

                user.set_unusable_password()
                user.save()

                ustatus = UserStatus(
                        user=user,
                        status=user_status.unconfirmed,
                        sign_in_key=make_sign_in_key(user))

                ustatus.save()

                from django.template.loader import render_to_string
                message = render_to_string("course/sign-in-email.txt", {
                    "user": user,
                    "sign_in_uri": request.build_absolute_uri(
                        reverse(
                            "relate-reset_password_stage2",
                            args=(user.id, ustatus.sign_in_key,))
                        + "?to_profile=1"),
                    "home_uri": request.build_absolute_uri(
                        reverse("relate-home"))
                    })

                from django.core.mail import send_mail
                send_mail(
                        string_concat("[", _("RELATE"), "] ",
                                     _("Verify your email")),
                        message,
                        settings.ROBOT_EMAIL_FROM,
                        recipient_list=[email])

                messages.add_message(request, messages.INFO,
                        _("Email sent. Please check your email and click "
                        "the link."))

                return redirect("relate-home")

    else:
        form = SignUpForm()

    return render(request, "generic-form.html", {
        "form_description": _("Sign up"),
        "form": form
        })


class ResetPasswordForm(StyledForm):
    email = forms.EmailField(required=True, label=_("Email"))

    def __init__(self, *args, **kwargs):
        super(ResetPasswordForm, self).__init__(*args, **kwargs)

        self.helper.add_input(
                Submit("submit", _("Send email")))


def reset_password(request):
    if settings.STUDENT_SIGN_IN_VIEW != "relate-sign_in_by_user_pw":
        raise SuspiciousOperation(
                _("password-based sign-in is not being used"))

    if request.method == 'POST':
        form = ResetPasswordForm(request.POST)
        if form.is_valid():

            email = form.cleaned_data["email"]
            try:
                user = get_user_model().objects.get(email__iexact=email)
            except ObjectDoesNotExist:
                user = None

            if user is None:
                messages.add_message(request, messages.ERROR,
                        _("That email address doesn't have an "
                          "associated user account. Are you "
                          "sure you've registered?"))
            else:
                from course.models import get_user_status
                ustatus = get_user_status(user)
                ustatus.sign_in_key = make_sign_in_key(user)
                ustatus.save()

                from django.template.loader import render_to_string
                message = render_to_string("course/sign-in-email.txt", {
                    "user": user,
                    "sign_in_uri": request.build_absolute_uri(
                        reverse(
                            "relate-reset_password_stage2",
                            args=(user.id, ustatus.sign_in_key,))),
                    "home_uri": request.build_absolute_uri(reverse("relate-home"))
                    })
                from django.core.mail import send_mail
                send_mail(
                        string_concat("[", _("RELATE"), "] ",
                                     _("Password reset")),
                        message,
                        settings.ROBOT_EMAIL_FROM,
                        recipient_list=[email])

                messages.add_message(request, messages.INFO,
                        _("Email sent. Please check your email and click "
                        "the link."))

                return redirect("relate-home")
    else:
        form = ResetPasswordForm()

    return render(request, "generic-form.html", {
        "form_description":
            _("Password reset on %(site_name)s")
            % {"site_name": _("RELATE")},
        "form": form
        })


class ResetPasswordStage2Form(StyledForm):
    password = forms.CharField(widget=forms.PasswordInput(),
                              label=_("Password"))
    password_repeat = forms.CharField(widget=forms.PasswordInput(),
                              label=_("Password confirmation"))

    def __init__(self, *args, **kwargs):
        super(ResetPasswordStage2Form, self).__init__(*args, **kwargs)

        self.helper.add_input(
                Submit("submit_user", _("Update")))

    def clean(self):
        cleaned_data = super(ResetPasswordStage2Form, self).clean()
        password = cleaned_data.get("password")
        password_repeat = cleaned_data.get("password_repeat")
        if password and password != password_repeat:
            self.add_error("password_repeat",
                    _("The two password fields didn't match."))


def reset_password_stage2(request, user_id, sign_in_key):
    if settings.STUDENT_SIGN_IN_VIEW != "relate-sign_in_by_user_pw":
        raise SuspiciousOperation(_("email-based sign-in is not being used"))

    if not check_sign_in_key(user_id=int(user_id), token=sign_in_key):
        messages.add_message(request, messages.ERROR,
                _("Invalid sign-in token. Perhaps you've used an old token "
                "email?"))
        raise PermissionDenied(_("invalid sign-in token"))

    if request.method == 'POST':
        form = ResetPasswordStage2Form(request.POST)
        if form.is_valid():
            from django.contrib.auth import authenticate, login
            user = authenticate(user_id=int(user_id), token=sign_in_key)
            if user is None:
                raise PermissionDenied(_("invalid sign-in token"))

            if not user.is_active:
                messages.add_message(request, messages.ERROR,
                        _("Account disabled."))
                raise PermissionDenied(_("invalid sign-in token"))

            user.set_password(form.cleaned_data["password"])
            user.save()

            login(request, user)

            if (not (user.first_name and user.last_name)
                    or "to_profile" in request.GET):
                messages.add_message(request, messages.INFO,
                        _("Successfully signed in. "
                        "Please complete your registration information below."))

                return redirect(
                       reverse("relate-user_profile")+"?first_login=1")
            else:
                messages.add_message(request, messages.INFO,
                        _("Successfully signed in."))

                return redirect("relate-home")
    else:
        form = ResetPasswordStage2Form()

    return render(request, "generic-form.html", {
        "form_description":
            _("Password reset on %(site_name)s")
            % {"site_name": _("RELATE")},
        "form": form
        })

# }}}


# {{{ email sign-in flow

class SignInByEmailForm(StyledForm):
    email = forms.EmailField(required=True, label=_("Email"),
            # For now, until we upgrade to a custom user model.
            max_length=30)

    def __init__(self, *args, **kwargs):
        super(SignInByEmailForm, self).__init__(*args, **kwargs)

        self.helper.add_input(
                Submit("submit", _("Send sign-in email")))


def sign_in_by_email(request):
    if settings.STUDENT_SIGN_IN_VIEW != "relate-sign_in_by_email":
        raise SuspiciousOperation(_("email-based sign-in is not being used"))

    if request.method == 'POST':
        form = SignInByEmailForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            user, created = get_user_model().objects.get_or_create(
                    email__iexact=email,
                    defaults=dict(username=email, email=email))

            if created:
                user.set_unusable_password()
                user.save()

            ustatus, ustatus_created = UserStatus.objects.get_or_create(
                    user=user,
                    defaults=dict(
                        status=user_status.unconfirmed,
                        sign_in_key=make_sign_in_key(user)))

            if not created:
                ustatus.sign_in_key = make_sign_in_key(user)
                ustatus.save()

            from django.template.loader import render_to_string
            message = render_to_string("course/sign-in-email.txt", {
                "user": user,
                "sign_in_uri": request.build_absolute_uri(
                    reverse(
                        "relate-sign_in_stage2_with_token",
                        args=(user.id, ustatus.sign_in_key,))),
                "home_uri": request.build_absolute_uri(reverse("relate-home"))
                })
            from django.core.mail import send_mail
            send_mail(
                    _("Your %(RELATE)s sign-in link") % {"RELATE": _("RELATE")},
                    message,
                    settings.ROBOT_EMAIL_FROM,
                    recipient_list=[email])

            messages.add_message(request, messages.INFO,
                    _("Email sent. Please check your email and click the link."))

            return redirect("relate-home")
    else:
        form = SignInByEmailForm()

    return render(request, "course/login-by-email.html", {
        "form_description": "",
        "form": form
        })


def sign_in_stage2_with_token(request, user_id, sign_in_key):
    if settings.STUDENT_SIGN_IN_VIEW != "relate-sign_in_by_email":
        raise SuspiciousOperation(_("email-based sign-in is not being used"))

    from django.contrib.auth import authenticate, login
    user = authenticate(user_id=int(user_id), token=sign_in_key)
    if user is None:
        messages.add_message(request, messages.ERROR,
                _("Invalid sign-in token. Perhaps you've used an old "
                "token email?"))
        raise PermissionDenied(_("invalid sign-in token"))

    if not user.is_active:
        messages.add_message(request, messages.ERROR,
                _("Account disabled."))
        raise PermissionDenied(_("invalid sign-in token"))

    from course.exam import may_sign_in
    if not may_sign_in(request, user):
        messages.add_message(request, messages.ERROR,
                _("Sign-in not allowed in this facility."))
        raise PermissionDenied(_("user not allowed to sign in in facility"))

    login(request, user)

    if not (user.first_name and user.last_name):
        messages.add_message(request, messages.INFO,
                _("Successfully signed in. "
                "Please complete your registration information below."))

        return redirect(
               reverse("relate-user_profile")+"?first_login=1")
    else:
        messages.add_message(request, messages.INFO,
                _("Successfully signed in."))

        return redirect("relate-home")

# }}}


# {{{ user profile

class UserForm(StyledModelForm):
    class Meta:
        model = get_user_model()
        fields = ("first_name", "last_name")

    def __init__(self, *args, **kwargs):
        super(UserForm, self).__init__(*args, **kwargs)

        self.helper.add_input(
                Submit("submit_user", _("Update")))


class UserStatusForm(StyledModelForm):
    class Meta:
        model = UserStatus
        fields = ("editor_mode",)

    def __init__(self, *args, **kwargs):
        super(UserStatusForm, self).__init__(*args, **kwargs)

        self.helper.add_input(
                Submit("submit_user_status", _("Update")))


def user_profile(request):
    if not request.user.is_authenticated():
        raise PermissionDenied()

    from course.models import get_user_status
    ustatus = get_user_status(request.user)

    user_form = None
    user_status_form = None

    if request.method == "POST":
        if "submit_user" in request.POST:
            user_form = UserForm(request.POST, instance=request.user)
            if user_form.is_valid():
                user_form.save()

                messages.add_message(request, messages.INFO,
                        _("Profile data saved."))
                if request.GET.get("first_login"):
                    return redirect("relate-home")

        if "submit_user_status" in request.POST:
            user_status_form = UserStatusForm(
                    request.POST, instance=ustatus)
            if user_status_form.is_valid():
                user_status_form.save()
                messages.add_message(request, messages.INFO,
                        _("Profile data saved."))
                if request.GET.get("first_login"):
                    return redirect("relate-home")

    if user_form is None:
        user_form = UserForm(instance=request.user)
    if user_status_form is None:
        user_status_form = UserStatusForm(instance=ustatus)

    return render(request, "user-profile-form.html", {
        "user_form": user_form,
        "user_status_form": user_status_form,
        })

# }}}


def get_role_and_participation(request, course):
    # "wake up" lazy object
    # http://stackoverflow.com/questions/20534577/int-argument-must-be-a-string-or-a-number-not-simplelazyobject  # noqa
    user = (request.user._wrapped
            if hasattr(request.user, '_wrapped')
            else request.user)

    if not user.is_authenticated():
        return participation_role.unenrolled, None

    participations = list(Participation.objects.filter(
            user=user,
            course=course,
            status=participation_status.active
            ))

    # The uniqueness constraint should have ensured that.
    assert len(participations) <= 1

    if len(participations) == 0:
        return participation_role.unenrolled, None

    participation = participations[0]
    if participation.status != participation_status.active:
        return participation_role.unenrolled, participation
    else:
        return participation.role, participation


# vim: foldmethod=marker
