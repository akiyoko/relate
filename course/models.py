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

from django.db import models
from django.contrib.auth.models import User
from django.utils.timezone import now
from django.core.urlresolvers import reverse
from django.core.exceptions import ValidationError

from course.constants import (  # noqa
        user_status, USER_STATUS_CHOICES,
        participation_role, PARTICIPATION_ROLE_CHOICES,
        participation_status, PARTICIPATION_STATUS_CHOICES,
        flow_permission, FLOW_PERMISSION_CHOICES,
        flow_session_expriration_mode, FLOW_SESSION_EXPIRATION_MODE_CHOICES,
        grade_aggregation_strategy, GRADE_AGGREGATION_STRATEGY_CHOICES,
        grade_state_change_types, GRADE_STATE_CHANGE_CHOICES,
        )


from jsonfield import JSONField


# {{{ user status

def get_user_status(user):
    try:
        return user.user_status
    except AttributeError:
        ustatus = UserStatus()
        ustatus.user = user
        ustatus.status = user_status.unconfirmed
        ustatus.save()

        return ustatus


class UserStatus(models.Model):
    user = models.OneToOneField(User, db_index=True, related_name="user_status")
    status = models.CharField(max_length=50,
            choices=USER_STATUS_CHOICES)
    sign_in_key = models.CharField(max_length=50,
            null=True, unique=True, db_index=True, blank=True)
    key_time = models.DateTimeField(default=now)

    class Meta:
        verbose_name_plural = "user statuses"
        ordering = ("key_time",)

    def __unicode__(self):
        return "User status for %s" % self.user

# }}}


# {{{ course

class Course(models.Model):
    identifier = models.CharField(max_length=200, unique=True,
            help_text="A course identifier. Alphanumeric with dashes, "
            "no spaces. This is visible in URLs and determines the location "
            "on your file system where the course's git repository lives.",
            db_index=True)

    hidden = models.BooleanField(
            default=True,
            help_text="Is the course only visible to course staff?")
    valid = models.BooleanField(
            default=True,
            help_text="Whether the course content has passed validation.")

    git_source = models.CharField(max_length=200, blank=True,
            help_text="A Git URL from which to pull course updates. "
            "If you're just starting out, enter "
            "<tt>git://github.com/inducer/courseflow-sample</tt> "
            "to get some sample content.")
    ssh_private_key = models.TextField(blank=True,
            help_text="An SSH private key to use for Git authentication")

    course_file = models.CharField(max_length=200,
            default="course.yml",
            help_text="Name of a YAML file in the git repository that contains "
            "the root course descriptor.")
    events_file = models.CharField(max_length=200,
            default="events.yml",
            help_text="Name of a YAML file in the git repository that contains "
            "calendar information.")

    enrollment_approval_required = models.BooleanField(
            default=False,
            help_text="If set, each enrolling student must be "
            "individually approved.")
    enrollment_required_email_suffix = models.CharField(
            max_length=200, blank=True, null=True,
            help_text="Enrollee's email addresses must end in the "
            "specified suffix, such as '@illinois.edu'.")

    email = models.EmailField(
            help_text="This email address will be used in the 'From' line "
            "of automated emails sent by CourseFlow. It will also receive "
            "notifications about required approvals.")

    # {{{ XMPP

    course_xmpp_id = models.CharField(max_length=200, blank=True, null=True,
            help_text="(Required only if the instant message feature is desired.) "
            "The Jabber/XMPP ID (JID) the course will use to sign in to an "
            "XMPP server.")
    course_xmpp_password = models.CharField(max_length=200, blank=True, null=True,
            help_text="(Required only if the instant message feature is desired.) "
            "The password to go with the JID above.")

    recipient_xmpp_id = models.CharField(max_length=200, blank=True, null=True,
            help_text="(Required only if the instant message feature is desired.) "
            "The JID to which instant messages will be sent.")

    # }}}

    active_git_commit_sha = models.CharField(max_length=200, null=False,
            blank=False)

    participants = models.ManyToManyField(User,
            through='Participation')

    def __unicode__(self):
        return self.identifier

    def get_absolute_url(self):
        return reverse("course.views.course_page", args=(self.identifier,))

# }}}


class Event(models.Model):
    """An event is an identifier that can be used to specify dates in
    course content.
    """

    course = models.ForeignKey(Course)
    kind = models.CharField(max_length=50,
            help_text="Should be lower_case_with_underscores, no spaces allowed.")
    ordinal = models.IntegerField(blank=True, null=True)

    time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)

    all_day = models.BooleanField(default=False,
            help_text="Only affects the rendering in the class calendar, "
            "in that a start time is not shown")

    shown_in_calendar = models.BooleanField(default=True)

    class Meta:
        ordering = ("course", "time")
        unique_together = (("course", "kind", "ordinal"))

    def __unicode__(self):
        if self.ordinal is not None:
            return "%s %s" % (self.kind, self.ordinal)
        else:
            return self.kind


# {{{ participation

class ParticipationTag(models.Model):
    course = models.ForeignKey(Course)
    name = models.CharField(max_length=100,
            help_text="Format: lower-case-with-hyphens")
    description = models.CharField(max_length=100)
    shown_to_participant = models.BooleanField(default=False)
    set_by_participant = models.BooleanField(default=False)

    def __unicode__(self):
        return "%s in %s" % (self.name, self.course)


class Participation(models.Model):
    user = models.ForeignKey(User)
    course = models.ForeignKey(Course)

    enroll_time = models.DateTimeField(default=now)
    role = models.CharField(max_length=50,
            choices=PARTICIPATION_ROLE_CHOICES)
    temporary_role = models.CharField(max_length=50,
            choices=PARTICIPATION_ROLE_CHOICES, null=True, blank=True)
    status = models.CharField(max_length=50,
            choices=PARTICIPATION_STATUS_CHOICES)

    time_factor = models.DecimalField(
            max_digits=10, decimal_places=2,
            default=1)

    preview_git_commit_sha = models.CharField(max_length=200, null=True,
            blank=True)

    tags = models.ManyToManyField(ParticipationTag, required=False)

    def __unicode__(self):
        return "%s in %s as %s" % (
                self.user, self.course, self.role)

    def clean(self):
        super(Participation, self).clean()

        for tag in self.tags.all():
            if tag.course != self.course:
                raise ValidationError(
                        "Tag '%s' is from different course than participation"
                        % tag)

    class Meta:
        unique_together = (("user", "course"),)
        ordering = ("course", "user")


class ParticipationPreapproval(models.Model):
    email = models.EmailField(max_length=254)
    course = models.ForeignKey(Course)
    role = models.CharField(max_length=50,
            choices=PARTICIPATION_ROLE_CHOICES)

    creator = models.ForeignKey(User, null=True)
    creation_time = models.DateTimeField(default=now, db_index=True)

    def __unicode__(self):
        return "%s in %s" % (self.email, self.course)

    class Meta:
        unique_together = (("course", "email"),)
        ordering = ("course", "email")

# }}}


class InstantFlowRequest(models.Model):
    course = models.ForeignKey(Course)
    flow_id = models.CharField(max_length=200)
    start_time = models.DateTimeField(default=now)
    end_time = models.DateTimeField()
    cancelled = models.BooleanField(default=False)


# {{{ flow session tracking

class FlowSession(models.Model):
    # This looks like it's redundant with 'participation', below--but it's not.
    # 'participation' is nullable.
    course = models.ForeignKey(Course)

    participation = models.ForeignKey(Participation, null=True, blank=True,
            db_index=True)
    active_git_commit_sha = models.CharField(max_length=200)
    flow_id = models.CharField(max_length=200, db_index=True)
    start_time = models.DateTimeField(default=now)
    completion_time = models.DateTimeField(null=True, blank=True)
    page_count = models.IntegerField(null=True, blank=True)

    in_progress = models.BooleanField(default=None)
    for_credit = models.BooleanField(default=None)
    access_rules_id = models.CharField(max_length=200, null=True,
            blank=True)
    expiration_mode = models.CharField(max_length=20, null=True,
            default=flow_session_expriration_mode.end,
            choices=FLOW_SESSION_EXPIRATION_MODE_CHOICES)

    # Non-normal: These fields can be recomputed, albeit at great expense.
    #
    # Looking up the corresponding GradeChange is also invalid because
    # some flow sessions are not for credit and still have results.

    points = models.DecimalField(max_digits=10, decimal_places=2,
            blank=True, null=True)
    max_points = models.DecimalField(max_digits=10, decimal_places=2,
            blank=True, null=True)
    result_comment = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ("course", "-start_time")

    def __unicode__(self):
        if self.participation is None:
            return "anonymous session %d on '%s'" % (
                    self.id,
                    self.flow_id)
        else:
            return "%s's session %d on '%s'" % (
                    self.participation.user,
                    self.id,
                    self.flow_id)

    def append_comment(self, s):
        if s is None:
            return

        if self.result_comment:
            self.result_comment += "\n" + s
        else:
            self.result_comment = s

    def points_percentage(self):
        if self.points is None:
            return None
        elif self.max_points:
            return 100*self.points/self.max_points
        else:
            return None

    def answer_visits(self):
        # only use this from templates
        from course.flow import assemble_answer_visits
        return assemble_answer_visits(self)


class FlowPageData(models.Model):
    flow_session = models.ForeignKey(FlowSession, related_name="page_data")
    ordinal = models.IntegerField()

    group_id = models.CharField(max_length=200)
    page_id = models.CharField(max_length=200)

    data = JSONField(null=True, blank=True)

    class Meta:
        unique_together = (("flow_session", "ordinal"),)
        verbose_name_plural = "flow page data"

    def __unicode__(self):
        return "Data for page '%s/%s' (%d) in %s" % (
                self.group_id,
                self.page_id,
                self.ordinal,
                self.flow_session)

    # Django's templates are a little daft. No arithmetic--really?
    def previous_ordinal(self):
        return self.ordinal - 1

    def next_ordinal(self):
        return self.ordinal + 1


class FlowPageVisit(models.Model):
    # This is redundant (because the FlowSession is available through
    # page_data), but it helps the admin site understand the link
    # and provide editing.
    flow_session = models.ForeignKey(FlowSession, db_index=True)

    page_data = models.ForeignKey(FlowPageData, db_index=True)
    visit_time = models.DateTimeField(default=now, db_index=True)
    remote_address = models.GenericIPAddressField(null=True, blank=True)

    is_synthetic = models.BooleanField(default=False)

    answer = JSONField(null=True, blank=True)
    is_graded_answer = models.NullBooleanField()

    def __unicode__(self):
        result = "'%s/%s' in '%s' on %s" % (
                self.page_data.group_id,
                self.page_data.page_id,
                self.flow_session,
                self.visit_time)

        if self.is_graded_answer:
            result += " (graded)"

        return result

    class Meta:
        # These must be distinguishable, to figure out what came later.
        unique_together = (("page_data", "visit_time"),)

    def get_most_recent_grade(self):
        grades = self.grades.order_by("-grade_time")[:1]

        for grade in grades:
            return grade

        return None

    def get_most_recent_feedback(self):
        grade = self.get_most_recent_grade()

        from course.page import AnswerFeedback
        if grade is not None:
            return AnswerFeedback.from_json(grade.feedback)
        else:
            return None

# }}}


#  {{{ flow page visit grade

class FlowPageVisitGrade(models.Model):
    visit = models.ForeignKey(FlowPageVisit, related_name="grades")

    # NULL means 'autograded'
    grader = models.ForeignKey(User, null=True, blank=True)
    grade_time = models.DateTimeField(db_index=True, default=now)

    graded_at_git_commit_sha = models.CharField(
            max_length=200, null=True, blank=True)

    grade_data = JSONField(null=True, blank=True)

    # This data should be recomputable, but we'll cache it here,
    # because it might be very expensive (container-launch expensive
    # for code questions, for example) to recompute.

    max_points = models.FloatField(null=True, blank=True,
            help_text="Point value of this question when receiving "
            "full credit.")
    correctness = models.FloatField(null=True, blank=True,
            help_text="Real number between zero and one (inclusively) "
            "indicating the degree of correctness of the answer.")

    # This JSON object has fields corresponding to
    # :class:`course.page.AnswerFeedback`, except for
    # :attr:`course.page.AnswerFeedback.correctness`, which is stored
    # separately for efficiency.

    feedback = JSONField(null=True, blank=True)

    def percentage(self):
        if self.correctness is not None:
            return 100*self.correctness
        else:
            return None

    def value(self):
        if self.correctness is not None and self.max_points is not None:
            return self.correctness * self.max_points
        else:
            return None

    class Meta:
        # These must be distinguishable, to figure out what came later.
        unique_together = (("visit", "grade_time"),)

        ordering = ("visit", "grade_time")

    def __unicode__(self):
        return "grade of %s: %s" % (
                self.visit, self.percentage())

# }}}

# }}}


# {{{ flow access

def validate_stipulations(stip):
    if stip is None:
        return

    if not isinstance(stip, dict):
        raise ValidationError("stipulations must be a dictionary")
    allowed_keys = set(["credit_percent", "allowed_session_count"])
    if not set(stip.keys()) <= allowed_keys:
        raise ValidationError("unrecognized keys in stipulations: %s"
                % ", ".join(set(stip.keys()) - allowed_keys))

    if "credit_percent" in stip and not isinstance(
            stip["credit_percent"], (int, float)):
        raise ValidationError("credit_percent must be a float")
    if ("allowed_session_count" in stip
            and (
                not isinstance(stip["allowed_session_count"], int)
                or stip["allowed_session_count"] < 0)):
        raise ValidationError("allowed_session_count must be a non-negative integer")


class FlowAccessException(models.Model):
    participation = models.ForeignKey(Participation, db_index=True)
    flow_id = models.CharField(max_length=200, blank=False, null=False)
    expiration = models.DateTimeField(blank=True, null=True)

    stipulations = JSONField(blank=True, null=True,
            help_text="A dictionary of the same things that can be added "
            "to a flow access rule, such as allowed_session_count or "
            "credit_percent. If not specified here, values will default "
            "to the stipulations in the course content.",
            validators=[validate_stipulations])

    creator = models.ForeignKey(User, null=True)
    creation_time = models.DateTimeField(default=now, db_index=True)

    is_sticky = models.BooleanField(
            default=False,
            help_text="Check if a flow started under this "
            "exception rule set should stay "
            "under this rule set until it is expired.")

    comment = models.TextField(blank=True, null=True)

    def __unicode__(self):
        return "Access exception for '%s' to '%s' in '%s'" % (
                self.participation.user, self.flow_id,
                self.participation.course)


class FlowAccessExceptionEntry(models.Model):
    exception = models.ForeignKey(FlowAccessException,
            related_name="entries")
    permission = models.CharField(max_length=50,
            choices=FLOW_PERMISSION_CHOICES)

    class Meta:
        verbose_name_plural = "flow access exception entries"

    def __unicode__(self):
        return self.permission

# }}}


# {{{ grading

class GradingOpportunity(models.Model):
    course = models.ForeignKey(Course)

    identifier = models.CharField(max_length=200, blank=False, null=False,
            help_text="A symbolic name for this grade. "
            "lower_case_with_underscores, no spaces.")
    name = models.CharField(max_length=200, blank=False, null=False,
            help_text="A human-readable identifier for the grade.")
    flow_id = models.CharField(max_length=200, blank=True, null=True,
            help_text="Flow identifier that this grading opportunity "
            "is linked to, if any")

    aggregation_strategy = models.CharField(max_length=20,
            choices=GRADE_AGGREGATION_STRATEGY_CHOICES)

    due_time = models.DateTimeField(default=None, blank=True, null=True)
    creation_time = models.DateTimeField(default=now)

    shown_in_grade_book = models.BooleanField(default=True)
    shown_in_student_grade_book = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "grading opportunities"
        ordering = ("course", "due_time", "identifier")
        unique_together = (("course", "identifier"),)

    def __unicode__(self):
        return "%s (%s) in %s" % (self.name, self.identifier, self.course)


class GradeChange(models.Model):
    """Per 'grading opportunity', each participant may accumulate multiple grades
    that are aggregated according to :attr:`GradingOpportunity.aggregation_strategy`.

    In addition, for each opportunity, grade changes are grouped by their 'attempt'
    identifier, where later grades with the same :attr:`attempt_id` supersede earlier
    ones.
    """
    opportunity = models.ForeignKey(GradingOpportunity)

    participation = models.ForeignKey(Participation)

    state = models.CharField(max_length=50,
            choices=GRADE_STATE_CHANGE_CHOICES)

    attempt_id = models.CharField(max_length=50, null=True, blank=True,
            help_text="Grade changes are grouped by their 'attempt ID' "
            "where later grades with the same attempt ID supersede earlier "
            "ones.")

    points = models.DecimalField(max_digits=10, decimal_places=2,
            blank=True, null=True)
    max_points = models.DecimalField(max_digits=10, decimal_places=2)

    comment = models.TextField(blank=True, null=True)

    due_time = models.DateTimeField(default=None, blank=True, null=True)

    creator = models.ForeignKey(User, null=True)
    grade_time = models.DateTimeField(default=now, db_index=True)

    flow_session = models.ForeignKey(FlowSession, null=True, blank=True,
            related_name="grade_changes")

    class Meta:
        ordering = ("opportunity", "participation", "grade_time")

    def __unicode__(self):
        return "%s %s on %s" % (self.participation, self.state,
                self.opportunity.name)

    def clean(self):
        if self.opportunity.course != self.participation.course:
            raise ValidationError("Participation and opportunity must live "
                    "in the same course")

    def percentage(self):
        if self.max_points is not None and self.points is not None:
            return 100*self.points/self.max_points
        else:
            return None

# }}}


# {{{ grade state machine

class GradeStateMachine(object):
    def __init__(self):
        self.opportunity = None

        self.state = None
        self._clear_grades()
        self.due_time = None
        self.last_graded_time = None
        self.last_report_time = None

        # applies to *all* grade changes
        self._last_grade_change_time = None

    def _clear_grades(self):
        self.state = None
        self.last_grade_time = None
        self.valid_percentages = []
        self.attempt_id_to_gchange = {}

    def _consume_grade_change(self, gchange, set_is_superseded):
        if self.opportunity is None:
            self.opportunity = gchange.opportunity
            self.due_time = self.opportunity.due_time
        else:
            assert self.opportunity.pk == gchange.opportunity.pk

        # check that times are increasing
        if self._last_grade_change_time is not None:
            assert gchange.grade_time > self._last_grade_change_time
            self._last_grade_change_time = gchange.grade_time

        if gchange.state == grade_state_change_types.graded:
            if self.state == grade_state_change_types.unavailable:
                raise ValueError("cannot accept grade once opportunity has been "
                        "marked 'unavailable'")
            if self.state == grade_state_change_types.exempt:
                raise ValueError("cannot accept grade once opportunity has been "
                        "marked 'exempt'")

            #if self.due_time is not None and gchange.grade_time > self.due_time:
                #raise ValueError("cannot accept grade after due date")

            self.state = gchange.state
            if gchange.attempt_id is not None:
                if (set_is_superseded and
                        gchange.attempt_id in self.attempt_id_to_gchange):
                    self.attempt_id_to_gchange[gchange.attempt_id] \
                            .is_superseded = True
                self.attempt_id_to_gchange[gchange.attempt_id] \
                        = gchange
            else:
                self.valid_percentages.append(gchange.percentage())

            self.last_graded_time = gchange.grade_time

        elif gchange.state == grade_state_change_types.unavailable:
            self._clear_grades()
            self.state = gchange.state

        elif gchange.state == grade_state_change_types.do_over:
            self._clear_grades()

        elif gchange.state == grade_state_change_types.exempt:
            self._clear_grades()
            self.state = gchange.state

        elif gchange.state == grade_state_change_types.report_sent:
            self.last_report_time = gchange.grade_time

        elif gchange.state == grade_state_change_types.extension:
            self.due_time = gchange.due_time

        elif gchange.state in [
                grade_state_change_types.grading_started,
                grade_state_change_types.retrieved,
                ]:
            pass
        else:
            raise RuntimeError("invalid grade change state '%s'" % gchange.state)

    def consume(self, iterable, set_is_superseded=False):
        for gchange in iterable:
            gchange.is_superseded = False
            self._consume_grade_change(gchange, set_is_superseded)

        self.valid_percentages.extend(
                gchange.percentage()
                for gchange in self.attempt_id_to_gchange.values()
                if gchange.percentage() is not None)

        del self.attempt_id_to_gchange

        return self

    def percentage(self):
        """
        :return: a percentage of achieved points, or *None*
        """
        if self.opportunity is None or not self.valid_percentages:
            return None

        strategy = self.opportunity.aggregation_strategy

        if strategy == grade_aggregation_strategy.max_grade:
            return max(self.valid_percentages)
        elif strategy == grade_aggregation_strategy.min_grade:
            return min(self.valid_percentages)
        elif strategy == grade_aggregation_strategy.avg_grade:
            return sum(self.valid_percentages)/len(self.valid_percentages)
        elif strategy == grade_aggregation_strategy.use_earliest:
            return self.valid_percentages[0]
        elif strategy == grade_aggregation_strategy.use_latest:
            return self.valid_percentages[-1]
        else:
            raise ValueError("invalid grade aggregation strategy '%s'" % strategy)

    def stringify_state(self):
        if self.state is None:
            return u"- ∅ -"
        elif self.state == grade_state_change_types.exempt:
            return "(exempt)"
        elif self.state == grade_state_change_types.graded:
            if self.valid_percentages:
                result = "%.1f%%" % self.percentage()
                if len(self.valid_percentages) > 1:
                    result += " (/%d)" % len(self.valid_percentages)
                return result
            else:
                return u"- ∅ -"
        else:
            return "(other state)"

    def stringify_percentage(self):
        if self.state == grade_state_change_types.graded:
            if self.valid_percentages:
                return "%.1f" % self.percentage()
            else:
                return u""
        else:
            return ""
# }}}


# {{{ flow <-> grading integration

def get_flow_grading_opportunity(course, flow_id, flow_desc):
    gopps = (GradingOpportunity.objects
            .filter(course=course)
            .filter(flow_id=flow_id))

    if gopps.count() == 0:
        gopp = GradingOpportunity()
        gopp.course = course
        gopp.identifier = "flow_"+flow_id.replace("-", "_")
        gopp.name = "Flow: %s" % flow_desc.title
        gopp.aggregation_strategy = flow_desc.grade_aggregation_strategy
        gopp.flow_id = flow_id
        gopp.save()

        return gopp
    else:
        gopp, = gopps
        return gopp

# }}}


# {{{ XMPP log

class InstantMessage(models.Model):
    participation = models.ForeignKey(Participation)
    text = models.CharField(max_length=200)
    time = models.DateTimeField(default=now)

    class Meta:
        ordering = ("participation__course", "time")

    def __unicode__(self):
        return "%s: %s" % (self.participation, self.text)

# }}}

# vim: foldmethod=marker
