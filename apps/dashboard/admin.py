from django.contrib import admin
# register all models here
from dashboard.models import *
from drugs.models import *
from users.models import *
from purchases.models import *
from pos.models import *
from users.models import User
 


admin.site.register(Sale)
admin.site.register(SaleItem)
admin.site.register(Purchase)
admin.site.register(PurchaseItem)
admin.site.register(User)


