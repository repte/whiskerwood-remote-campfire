#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "CampfireAuthoringProbe.generated.h"

class UBlueprint;

UCLASS()
class UCampfireAuthoringProbe final : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    // Compiles transient graphs only. It never executes their game calls.
    UFUNCTION(BlueprintCallable, Category = "Campfire Authoring Probe")
    static FString RunProof();

    UFUNCTION(BlueprintCallable, Category = "Campfire Authoring Probe")
    static FString EnableAuthoring();

    UFUNCTION(BlueprintCallable, Category = "Campfire Authoring Probe")
    static FString AddRuntimeBridge(UBlueprint* Blueprint);
};
