#include "CampfireAuthoringProbe.h"
#include "Modules/ModuleManager.h"

class FCampfireProbeEditorModule final : public IModuleInterface
{
public:
    virtual void StartupModule() override
    {
        UE_LOG(LogTemp, Display, TEXT("CAMPFIRE_AUTHORING_ACCESS %s"), *UCampfireAuthoringProbe::EnableAuthoring());
    }
};

IMPLEMENT_MODULE(FCampfireProbeEditorModule, CampfireProbeEditor)
