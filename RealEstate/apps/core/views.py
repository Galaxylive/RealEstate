import json

from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import login as auth_login
from django.db import transaction
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views.generic import View
from django import forms
from django.http import HttpResponse

from RealEstate.apps.core.models import Category, Couple, Grade, House, Homebuyer, Realtor, User
from RealEstate.apps.pending.models import PendingCouple, PendingHomebuyer
from RealEstate.apps.pending.forms import InviteHomebuyerForm


def login(request, *args, **kwargs):
    """
    If the user is already logged in and they navigate to the login URL,
    just redirect them home. Otherwise just delegate to the default
    Django login view.
    """
    if request.user.is_authenticated():
        return redirect('home')
    return auth_login(request, *args, **kwargs)


class BaseView(View):
    """
    All subclassed views will redirect to the login view if not logged in.
    By default, both Homebuyers and Realtors are allowed to see all views.
    However this can be overridden by subclassed views to make them
    Homebuyer or Realtor only.
    """
    _USER_TYPES_ALLOWED = User._ALL_TYPES_ALLOWED

    def _permission_check(self, request, role, *args, **kwargs):
        """
        Override this in subclassed views if the view needs more granular
        permissions than the simple Homebuyer/Realtor check.
        """
        return True

    @method_decorator(login_required)
    def dispatch(self, request, *args, **kwargs):
        role = request.user.role_object
        if role and role.role_type in self._USER_TYPES_ALLOWED:
            if self._permission_check(request, role, *args, **kwargs):
                return super(BaseView, self).dispatch(request, *args, **kwargs)
        raise PermissionDenied


class HomeView(BaseView):
    """
    View for the home page, which should render different templates based
    on whether or not the the logged in User is a Realtor or Homebuyer.
    """
    def _invite_homebuyer(self, request, pending_couple, email):
        """
        Create the PendingHomebuyer instance and attach it to the
        PendingCouple.  Then send out the email invite and flash a message
        to the user that the invite has been sent.
        """
        homebuyer = PendingHomebuyer.objects.create(
            email=email,
            pending_couple=pending_couple)
        homebuyer.send_email_invite(request)

    
    def get(self, request, *args, **kwargs):
        global pendingHomebuyer
        couple = Couple.objects.filter(homebuyer__user=request.user)
        realtor = Realtor.objects.filter(user=request.user)
        if couple:
            house = House.objects.filter(couple=couple)
            return render(request, 'core/homebuyerHome.html', {'couple': couple, 'house': house})
        elif realtor:
            couples = Couple.objects.filter(realtor=realtor)
            pendingCouples = PendingCouple.objects.filter(realtor=realtor)
            house = House.objects.filter(couple=couple)
            # Couple data is a list of touples [(couple1, homebuyers), (couple2, homebuyers)]
            # There may be a better way to get homebuyers straight from couples, but I didn't see
            # it in the model.
            coupleData = []
            for couple in couples:
                homebuyer = Homebuyer.objects.filter(couple=couple)
                coupleData.append((couple, homebuyer, False))
            for pendingCouple in pendingCouples:
                pendingHomebuyer = PendingHomebuyer.objects.filter(pending_couple=pendingCouple)
                coupleData.append((pendingCouple, pendingHomebuyer, True))
            return render(request, 'core/realtorHome.html', {'couples': coupleData, 'house': house, 'realtor': realtor,
                                                             'form': InviteHomebuyerForm() })
        else:
            raise Exception("Neither a Homebuyer nor a Realtor")
    def post(self, request, *args, **kwargs):
        realtor = Realtor.objects.filter(user=request.user)
        couple = Couple.objects.filter(homebuyer__user=request.user)

        if couple:
            #do stuff
            house = House.objects.filter(couple=couple)
            return render(request, 'core/homebuyerHome.html', {'couple': couples, 'house': house})
            
        elif realtor:
            couples = Couple.objects.filter(realtor=realtor)
            pendingCouples = PendingCouple.objects.filter(realtor=realtor)
            house = House.objects.filter(couple=couple)
            form = InviteHomebuyerForm(request.POST)
            if form.is_valid():
                first_email = form.cleaned_data.get('first_email')
                second_email = form.cleaned_data.get('second_email')
                with transaction.atomic():
                    pending_couple = PendingCouple.objects.create(
                        realtor=request.user.realtor)
                    self._invite_homebuyer(request, pending_couple, first_email)
                    self._invite_homebuyer(request, pending_couple, second_email)
            
            coupleData = []
            for couple in couples:
                homebuyer = Homebuyer.objects.filter(couple=couple)
                coupleData.append((couple, homebuyer, False))
            for pendingCouple in pendingCouples:
                pendingHomebuyer = PendingHomebuyer.objects.filter(pending_couple=pendingCouple)
                coupleData.append((pendingCouple, pendingHomebuyer, True))
                
            return render(request, 'core/realtorHome.html', {'couples': coupleData, 'house': house, 'realtor': realtor,
                                                             'form': InviteHomebuyerForm() })
        else:
            raise Exception("Neither a Homebuyer nor a Realtor")
            
class EvalView(BaseView):
    """
    View for the Home Evaluation Page. Currently, this page is decoupled
    from the rest of the app and uses static elements in the database.
    """
    template_name = 'core/houseEval.html'

    def _permission_check(self, request, role, *args, **kwargs):
        """
        For a given House instance, only allow the user to view the page if
        its for a related Homebuyer. This prevents users from grading other
        peoples houses.
        """
        if role.role_type == 'Homebuyer':
            house_id = kwargs.get('house_id', None)
            if role.couple.house_set.filter(id=house_id).exists():
                return True
        return False

    def _score_context(self):
        score_field = Grade._meta.get_field('score')
        score_choices = dict(score_field.choices)
        min_score = min(score for score in score_choices)
        max_score = max(score for score in score_choices)
        min_choice = score_choices[min_score]
        max_choice = score_choices[max_score]
        return {
            'min_score': min_score,
            'max_score': max_score,
            'min_choice': min_choice,
            'max_choice': max_choice,
            'default_score': score_field.default,
            'js_scores': json.dumps(score_choices),
        }

    def get(self, request, *args, **kwargs):
        homebuyer = request.user.role_object
        couple = Couple.objects.filter(homebuyer__user=request.user)
        categories = Category.objects.filter(couple=couple)
        house = get_object_or_404(House.objects.filter(id=kwargs["house_id"]))
        grades = Grade.objects.filter(house=house, homebuyer=homebuyer)

        # Merging grades and categories to provide object with both
        # information. Data Structure: [(cat1, score1), (cat2, score2), ...]
        graded = []
        for category in categories:
            missing = True
            for grade in grades:
                if grade.category.id is category.id:
                    graded.append((category, grade.score))
                    missing = False
                    break
            if missing:
                graded.append((category, None))

        context = {
            'couple': couple,
            'house' : house,
            'grades': graded,
        }
        context.update(self._score_context())
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        """
        Depending on what functionality we want, the post may be more of a
        redirect back to the home page. In that case, much of this code will
        leave. In the meantime, it saves new data, recreates the same form and
        posts a success message.
        """
        if not request.is_ajax():
            raise PermissionDenied

        homebuyer = Homebuyer.objects.filter(user_id=request.user.id)
        house = get_object_or_404(House.objects.filter(id=kwargs["house_id"]))
        id = request.POST['category']
        score = request.POST['score']
        category = Category.objects.get(id=id)
        grade, created = Grade.objects.update_or_create(
            homebuyer=homebuyer.first(), category=category, house=house,
            defaults={'score': int(score)})
        response_data = {
            'id': str(id),
            'score': str(score)
        }
        return HttpResponse(json.dumps(response_data),
                            content_type="application/json")
