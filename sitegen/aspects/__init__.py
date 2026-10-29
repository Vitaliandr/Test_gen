from sitegen.aspects import registry
from sitegen.aspects.legal import LegalAspect
from sitegen.aspects.privacy import PrivacyAspect
from sitegen.aspects.references import ReferencesAspect
from sitegen.aspects.requisites import RequisitesAspect
from sitegen.aspects.security import SecurityAspect

#порядок важен: так генерим и так стоят в меню
for _aspect in (LegalAspect(), RequisitesAspect(), PrivacyAspect(), SecurityAspect(), ReferencesAspect()):
    registry.register(_aspect)
