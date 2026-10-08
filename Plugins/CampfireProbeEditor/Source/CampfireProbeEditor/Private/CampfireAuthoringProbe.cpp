#include "CampfireAuthoringProbe.h"

#include "Dom/JsonObject.h"
#include "EdGraph/EdGraph.h"
#include "EdGraphSchema_K2.h"
#include "Engine/Blueprint.h"
#include "Engine/BlueprintGeneratedClass.h"
#include "GameFramework/Actor.h"
#include "K2Node_BreakStruct.h"
#include "K2Node_CallFunction.h"
#include "K2Node_DynamicCast.h"
#include "K2Node_FunctionEntry.h"
#include "K2Node_FunctionResult.h"
#include "K2Node_GetArrayItem.h"
#include "K2Node_IfThenElse.h"
#include "K2Node_SetFieldsInStruct.h"
#include "K2Node_VariableGet.h"
#include "K2Node_VariableSet.h"
#include "Kismet2/BlueprintEditorUtils.h"
#include "Kismet2/KismetEditorUtilities.h"
#include "Kismet/BlueprintMapLibrary.h"
#include "KismetCompiler.h"
#include "Misc/OutputDevice.h"
#include "Modules/ModuleManager.h"
#include "ScriptDisassembler.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/UnrealType.h"

namespace
{
    struct FBridgeContract
    {
        UClass* Systems = nullptr;
        UClass* Granary = nullptr;
        UClass* Heater = nullptr;
        UClass* Controller = nullptr;
        UClass* ModAPI = nullptr;
        UClass* Tracker = nullptr;
        FStructProperty* WorldMeta = nullptr;
        FObjectPropertyBase* Primary = nullptr;
        FFloatProperty* Remaining = nullptr;
        FArrayProperty* History = nullptr;
        FStructProperty* Day = nullptr;
        FStructProperty* Summary = nullptr;
        FMapProperty* Flows = nullptr;
        FStructProperty* Collection = nullptr;
        UEnum* FlowType = nullptr;
        UFunction* Give = nullptr;
        UFunction* LoadCDO = nullptr;

        bool Resolve()
        {
            FModuleManager::LoadModuleChecked<IModuleInterface>(TEXT("Suzie"));
            Systems = FindObject<UClass>(nullptr, TEXT("/Script/ProjectArco.ArcoSystems"));
            Granary = FindObject<UClass>(nullptr, TEXT("/Script/ProjectArco.GranaryResourceBuilding"));
            Heater = FindObject<UClass>(nullptr, TEXT("/Script/ProjectArco.FueledHeater"));
            Controller = FindObject<UClass>(nullptr, TEXT("/Script/ProjectArco.PlayerController_Play"));
            ModAPI = FindObject<UClass>(nullptr, TEXT("/Script/SystemCore.ModAPI"));
            Tracker = FindObject<UClass>(nullptr, TEXT("/Script/ProjectArco.StatisticsTracker"));
            if (!Systems || !Granary || !Heater || !Controller || !ModAPI || !Tracker) return false;
            WorldMeta = FindFProperty<FStructProperty>(Systems, TEXT("m_worldMeta"));
            Primary = WorldMeta ? FindFProperty<FObjectPropertyBase>(WorldMeta->Struct, TEXT("primaryWarehouse")) : nullptr;
            Remaining = FindFProperty<FFloatProperty>(Heater, TEXT("m_burnTimeRemaining"));
            Give = Controller->FindFunctionByName(TEXT("Arco_GiveResource"));
            LoadCDO = ModAPI->FindFunctionByName(TEXT("LoadCdoOfClass"));
            History = FindFProperty<FArrayProperty>(Tracker, TEXT("m_combinedStatsHistory"));
            Day = History ? CastField<FStructProperty>(History->Inner) : nullptr;
            Summary = Day ? FindFProperty<FStructProperty>(Day->Struct, TEXT("resourcesSummary")) : nullptr;
            Flows = Summary ? FindFProperty<FMapProperty>(Summary->Struct, TEXT("m_resourceFlows")) : nullptr;
            Collection = Flows ? CastField<FStructProperty>(Flows->ValueProp) : nullptr;
            FEnumProperty* EnumKey = Flows ? CastField<FEnumProperty>(Flows->KeyProp) : nullptr;
            FByteProperty* ByteKey = Flows ? CastField<FByteProperty>(Flows->KeyProp) : nullptr;
            FlowType = EnumKey ? EnumKey->GetEnum() : (ByteKey ? ByteKey->Enum.Get() : nullptr);
            return WorldMeta && Primary && Primary->PropertyClass == Granary && Remaining && Give && LoadCDO
                && Give->GetOuter() == Controller && LoadCDO->GetOuter() == ModAPI
                && FindFProperty<FStrProperty>(Give, TEXT("ResourceName"))
                && FindFProperty<FIntProperty>(Give, TEXT("count"))
                && Give->NumParms == 2 && History && Day && Summary && Flows && Collection && FlowType
                && FlowType->GetNameStringByValue(4) == TEXT("CONSTRUCTION")
                && Collection->Struct->GetName() == TEXT("ResourceCollection");
        }

        void Enable() const
        {
            // These are Suzie editor stubs, never the running game's objects.
            for (FProperty* Property : { static_cast<FProperty*>(WorldMeta), static_cast<FProperty*>(Primary),
                static_cast<FProperty*>(Remaining), static_cast<FProperty*>(History), static_cast<FProperty*>(Summary), static_cast<FProperty*>(Flows) })
            {
                Property->SetPropertyFlags(CPF_BlueprintVisible);
                Property->ClearPropertyFlags(CPF_BlueprintReadOnly);
            }
            for (UFunction* Function : { Give, LoadCDO })
            {
                Function->FunctionFlags &= ~(FUNC_Private | FUNC_Protected);
                Function->FunctionFlags |= FUNC_Public | FUNC_BlueprintCallable;
            }
        }
    };

    class FProbeOutput final : public FOutputDevice
    {
    public:
        FString Text;
        virtual void Serialize(const TCHAR* Message, ELogVerbosity::Type, const FName&) override
        {
            Text += Message;
            Text += TEXT("\n");
        }
    };

    FString Json(const TSharedRef<FJsonObject>& Report)
    {
        FString Result;
        FJsonSerializer::Serialize(Report, TJsonWriterFactory<>::Create(&Result));
        return Result;
    }

    FEdGraphPinType ObjectPin(UClass* Class)
    {
        FEdGraphPinType Type;
        Type.PinCategory = UEdGraphSchema_K2::PC_Object;
        Type.PinSubCategoryObject = Class;
        return Type;
    }

    FEdGraphPinType ScalarPin(FName Category)
    {
        FEdGraphPinType Type;
        Type.PinCategory = Category;
        return Type;
    }

    FEdGraphPinType StructPin(UScriptStruct* Struct)
    {
        FEdGraphPinType Type;
        Type.PinCategory = UEdGraphSchema_K2::PC_Struct;
        Type.PinSubCategoryObject = Struct;
        return Type;
    }

    template<typename NodeType, typename ConfigureType>
    NodeType* AddNode(UEdGraph* Graph, ConfigureType Configure)
    {
        NodeType* Node = NewObject<NodeType>(Graph);
        Graph->AddNode(Node, false, false);
        Node->CreateNewGuid();
        Configure(Node);
        Node->AllocateDefaultPins();
        return Node;
    }

    UEdGraph* AddFunction(UBlueprint* Blueprint, FName Name, UK2Node_FunctionEntry*& Entry)
    {
        UEdGraph* Graph = FBlueprintEditorUtils::CreateNewGraph(
            Blueprint, Name, UEdGraph::StaticClass(), UEdGraphSchema_K2::StaticClass());
        FBlueprintEditorUtils::AddFunctionGraph<UClass>(Blueprint, Graph, true, nullptr);
        for (UEdGraphNode* Node : Graph->Nodes)
        {
            if (UK2Node_FunctionEntry* Candidate = Cast<UK2Node_FunctionEntry>(Node))
            {
                Entry = Candidate;
                Entry->SetExtraFlags(FUNC_Public | FUNC_BlueprintCallable);
                break;
            }
        }
        return Graph;
    }

    bool Connect(UEdGraph* Graph, UEdGraphPin* From, UEdGraphPin* To, FString& Error)
    {
        if (From && To && Graph->GetSchema()->TryCreateConnection(From, To)) return true;
        Error = FString::Printf(TEXT("Cannot connect %s to %s"),
            From ? *From->GetName() : TEXT("<missing>"), To ? *To->GetName() : TEXT("<missing>"));
        return false;
    }

    FString Disassemble(UFunction* Function)
    {
        FProbeOutput Output;
        FKismetBytecodeDisassembler Disassembler(Output);
        Disassembler.DisassembleStructure(Function);
        return Output.Text;
    }

    UK2Node_BreakStruct* BreakMember(UEdGraph* Graph, UScriptStruct* Struct, FName Member)
    {
        UK2Node_BreakStruct* Node = AddNode<UK2Node_BreakStruct>(Graph, [Struct](UK2Node_BreakStruct* NewNode)
        {
            NewNode->StructType = Struct;
        });
        for (FOptionalPinFromProperty& Pin : Node->ShowPinForProperties) Pin.bShowPin = Pin.PropertyName == Member;
        Node->ReconstructNode();
        return Node;
    }

    UEdGraphPin* StatsMap(UEdGraph* Graph, UK2Node_FunctionEntry* Entry, const FBridgeContract& Contract, FString& Error)
    {
        UEdGraphPin* TrackerInput = Entry->CreateUserDefinedPin(TEXT("Tracker"), ObjectPin(Contract.Tracker), EGPD_Output);
        UEdGraphPin* DayInput = Entry->CreateUserDefinedPin(TEXT("DayIndex"), ScalarPin(UEdGraphSchema_K2::PC_Int), EGPD_Output);
        UK2Node_VariableGet* HistoryGet = AddNode<UK2Node_VariableGet>(Graph, [&Contract](UK2Node_VariableGet* Node)
        {
            Node->VariableReference.SetExternalMember(TEXT("m_combinedStatsHistory"), Contract.Tracker);
        });
        UK2Node_GetArrayItem* GetDay = AddNode<UK2Node_GetArrayItem>(Graph, [](UK2Node_GetArrayItem* Node)
        {
            // SetDesiredReturnType is not exported from BlueprintGraph.
            if (FBoolProperty* ByRef = FindFProperty<FBoolProperty>(Node->GetClass(), TEXT("bReturnByRefDesired")))
                ByRef->SetPropertyValue_InContainer(Node, true);
        });
        UK2Node_BreakStruct* BreakDay = BreakMember(Graph, Contract.Day->Struct, TEXT("resourcesSummary"));
        UK2Node_BreakStruct* BreakSummary = BreakMember(Graph, Contract.Summary->Struct, TEXT("m_resourceFlows"));
        if (!Connect(Graph, TrackerInput, HistoryGet->FindPin(UEdGraphSchema_K2::PN_Self), Error)
            || !Connect(Graph, HistoryGet->FindPin(TEXT("m_combinedStatsHistory")), GetDay->GetTargetArrayPin(), Error)
            || !Connect(Graph, DayInput, GetDay->GetIndexPin(), Error)
            || !Connect(Graph, GetDay->GetResultPin(), BreakDay->FindPin(Contract.Day->Struct->GetFName()), Error)
            || !Connect(Graph, BreakDay->FindPin(TEXT("resourcesSummary")), BreakSummary->FindPin(Contract.Summary->Struct->GetFName()), Error)) return nullptr;
        return BreakSummary->FindPin(TEXT("m_resourceFlows"));
    }

    UK2Node_CallFunction* MapCall(UEdGraph* Graph, FName FunctionName, UEdGraphPin* Map, const FBridgeContract& Contract, FString& Error)
    {
        UFunction* Function = UBlueprintMapLibrary::StaticClass()->FindFunctionByName(FunctionName);
        if (!Function)
        {
            Error = TEXT("Missing engine map function.");
            return nullptr;
        }
        UK2Node_CallFunction* Node = AddNode<UK2Node_CallFunction>(Graph, [Function](UK2Node_CallFunction* NewNode) { NewNode->SetFromFunction(Function); });
        if (!Connect(Graph, Map, Node->FindPin(TEXT("TargetMap")), Error)) return nullptr;
        UEdGraphPin* Key = Node->FindPin(TEXT("Key"));
        if (!Key)
        {
            Error = TEXT("Missing map key pin.");
            return nullptr;
        }
        Graph->GetSchema()->TrySetDefaultValue(*Key, Contract.FlowType->GetNameStringByValue(4));
        return Node;
    }
}

FString UCampfireAuthoringProbe::RunProof()
{
    UBlueprint* Blueprint = FKismetEditorUtilities::CreateBlueprint(
        AActor::StaticClass(), GetTransientPackage(),
        MakeUniqueObjectName(GetTransientPackage(), UBlueprint::StaticClass(), TEXT("BP_CampfireAuthoringProof")), BPTYPE_Normal);
    if (Blueprint) Blueprint->SetFlags(RF_Transient);
    return AddRuntimeBridge(Blueprint);
}

FString UCampfireAuthoringProbe::EnableAuthoring()
{
    const TSharedRef<FJsonObject> Report = MakeShared<FJsonObject>();
    FBridgeContract Contract;
    const bool bValid = Contract.Resolve();
    if (bValid) Contract.Enable();
    Report->SetBoolField(TEXT("success"), bValid);
    Report->SetStringField(TEXT("scope"), TEXT("Validated Suzie editor-stub flags for this editor session only."));
    if (!bValid) Report->SetStringField(TEXT("error"), TEXT("Native authoring contract changed; no flags altered."));
    return Json(Report);
}

FString UCampfireAuthoringProbe::AddRuntimeBridge(UBlueprint* Blueprint)
{
    const TSharedRef<FJsonObject> Report = MakeShared<FJsonObject>();
    Report->SetBoolField(TEXT("success"), false);
    Report->SetBoolField(TEXT("native_action_executed"), false);
    Report->SetBoolField(TEXT("assets_saved"), false);
    const auto Fail = [&Report](const FString& Message)
    {
        Report->SetStringField(TEXT("error"), Message);
        return Json(Report);
    };

    if (!IsValid(Blueprint)) return Fail(TEXT("A valid Blueprint is required."));
    FBridgeContract Contract;
    if (!Contract.Resolve()) return Fail(TEXT("Native authoring contract changed."));
    Contract.Enable();
    UClass* Systems = Contract.Systems;
    UClass* Granary = Contract.Granary;
    UClass* Heater = Contract.Heater;
    UClass* Controller = Contract.Controller;
    UClass* ModAPI = Contract.ModAPI;
    FStructProperty* WorldMeta = Contract.WorldMeta;
    UFunction* Give = Contract.Give;
    UFunction* LoadCDO = Contract.LoadCDO;

    const TArray<FName> FunctionNames = { TEXT("CfSetPrimaryWarehouse"), TEXT("CfSetBurnTime"), TEXT("CfGrantWood"),
        TEXT("CfReadConstructionStats"), TEXT("CfRestoreConstructionStats") };
    for (UEdGraph* Graph : Blueprint->FunctionGraphs)
        if (FunctionNames.Contains(Graph->GetFName())) return Fail(TEXT("Runtime bridge already exists; use a fresh Blueprint."));

    FString Error;
    UK2Node_FunctionEntry* Entry = nullptr;
    UEdGraph* PrimaryGraph = AddFunction(Blueprint, TEXT("CfSetPrimaryWarehouse"), Entry);
    if (!Entry) return Fail(TEXT("Missing primary-warehouse function entry."));
    UEdGraphPin* SystemsInput = Entry->CreateUserDefinedPin(TEXT("Systems"), ObjectPin(Systems), EGPD_Output);
    UEdGraphPin* WarehouseInput = Entry->CreateUserDefinedPin(TEXT("Warehouse"), ObjectPin(Granary), EGPD_Output);
    UK2Node_VariableGet* MetaGet = AddNode<UK2Node_VariableGet>(PrimaryGraph, [Systems](UK2Node_VariableGet* Node)
    {
        Node->VariableReference.SetExternalMember(TEXT("m_worldMeta"), Systems);
    });
    UK2Node_SetFieldsInStruct* SetPrimary = AddNode<UK2Node_SetFieldsInStruct>(PrimaryGraph, [WorldMeta](UK2Node_SetFieldsInStruct* Node)
    {
        Node->StructType = WorldMeta->Struct;
    });
    for (FOptionalPinFromProperty& Pin : SetPrimary->ShowPinForProperties)
        Pin.bShowPin = Pin.PropertyName == TEXT("primaryWarehouse");
    SetPrimary->ReconstructNode();
    if (!Connect(PrimaryGraph, Entry->FindPin(UEdGraphSchema_K2::PN_Then), SetPrimary->FindPin(UEdGraphSchema_K2::PN_Execute), Error)
        || !Connect(PrimaryGraph, SystemsInput, MetaGet->FindPin(UEdGraphSchema_K2::PN_Self), Error)
        || !Connect(PrimaryGraph, MetaGet->FindPin(TEXT("m_worldMeta")), SetPrimary->FindPin(TEXT("StructRef")), Error)
        || !Connect(PrimaryGraph, WarehouseInput, SetPrimary->FindPin(TEXT("primaryWarehouse")), Error)) return Fail(Error);

    Entry = nullptr;
    UEdGraph* FuelGraph = AddFunction(Blueprint, TEXT("CfSetBurnTime"), Entry);
    if (!Entry) return Fail(TEXT("Missing fuel function entry."));
    UEdGraphPin* HeaterInput = Entry->CreateUserDefinedPin(TEXT("Heater"), ObjectPin(Heater), EGPD_Output);
    FEdGraphPinType FloatType;
    FloatType.PinCategory = UEdGraphSchema_K2::PC_Real;
    FloatType.PinSubCategory = UEdGraphSchema_K2::PC_Float;
    UEdGraphPin* RemainingInput = Entry->CreateUserDefinedPin(TEXT("Remaining"), FloatType, EGPD_Output);
    UK2Node_VariableSet* SetFuel = AddNode<UK2Node_VariableSet>(FuelGraph, [Heater](UK2Node_VariableSet* Node)
    {
        Node->VariableReference.SetExternalMember(TEXT("m_burnTimeRemaining"), Heater);
    });
    if (!Connect(FuelGraph, Entry->FindPin(UEdGraphSchema_K2::PN_Then), SetFuel->FindPin(UEdGraphSchema_K2::PN_Execute), Error)
        || !Connect(FuelGraph, HeaterInput, SetFuel->FindPin(UEdGraphSchema_K2::PN_Self), Error)
        || !Connect(FuelGraph, RemainingInput, SetFuel->FindPin(TEXT("m_burnTimeRemaining")), Error)) return Fail(Error);

    Entry = nullptr;
    UEdGraph* GrantGraph = AddFunction(Blueprint, TEXT("CfGrantWood"), Entry);
    if (!Entry) return Fail(TEXT("Missing native-call function entry."));
    UEdGraphPin* ApiInput = Entry->CreateUserDefinedPin(TEXT("ModApi"), ObjectPin(ModAPI), EGPD_Output);
    UEdGraphPin* ContextInput = Entry->CreateUserDefinedPin(TEXT("WorldContext"), ObjectPin(UObject::StaticClass()), EGPD_Output);
    UEdGraphPin* CountInput = Entry->CreateUserDefinedPin(TEXT("Count"), ScalarPin(UEdGraphSchema_K2::PC_Int), EGPD_Output);
    UK2Node_CallFunction* CdoCall = AddNode<UK2Node_CallFunction>(GrantGraph, [LoadCDO](UK2Node_CallFunction* Node) { Node->SetFromFunction(LoadCDO); });
    UK2Node_DynamicCast* CastCdo = AddNode<UK2Node_DynamicCast>(GrantGraph, [Controller](UK2Node_DynamicCast* Node)
    {
        Node->TargetType = Controller;
        Node->SetPurity(true);
    });
    UK2Node_CallFunction* GiveCall = AddNode<UK2Node_CallFunction>(GrantGraph, [Give](UK2Node_CallFunction* Node) { Node->SetFromFunction(Give); });
    UEdGraphPin* ClassPin = CdoCall->FindPin(TEXT("targetClass"));
    UEdGraphPin* ResourcePin = GiveCall->FindPin(TEXT("ResourceName"));
    UEdGraphPin* CountPin = GiveCall->FindPin(TEXT("count"));
    if (!ClassPin || !ResourcePin || !CountPin) return Fail(TEXT("Native-call parameter pins are missing."));
    GrantGraph->GetSchema()->TrySetDefaultObject(*ClassPin, Controller);
    GrantGraph->GetSchema()->TrySetDefaultValue(*ResourcePin, TEXT("wood"));
    if (!Connect(GrantGraph, ApiInput, CdoCall->FindPin(UEdGraphSchema_K2::PN_Self), Error)
        || !Connect(GrantGraph, ContextInput, CdoCall->FindPin(TEXT("WorldContext")), Error)
        || !Connect(GrantGraph, CountInput, CountPin, Error)
        || !Connect(GrantGraph, CdoCall->GetReturnValuePin(), CastCdo->GetCastSourcePin(), Error)
        || !Connect(GrantGraph, CastCdo->GetCastResultPin(), GiveCall->FindPin(UEdGraphSchema_K2::PN_Self), Error)) return Fail(Error);
    UEdGraphPin* Exec = Entry->FindPin(UEdGraphSchema_K2::PN_Then);
    if (UEdGraphPin* LoadExec = CdoCall->FindPin(UEdGraphSchema_K2::PN_Execute))
    {
        if (!Connect(GrantGraph, Exec, LoadExec, Error)) return Fail(Error);
        Exec = CdoCall->FindPin(UEdGraphSchema_K2::PN_Then);
    }
    if (!Connect(GrantGraph, Exec, GiveCall->FindPin(UEdGraphSchema_K2::PN_Execute), Error)) return Fail(Error);

    Entry = nullptr;
    UEdGraph* ReadGraph = AddFunction(Blueprint, TEXT("CfReadConstructionStats"), Entry);
    if (!Entry) return Fail(TEXT("Missing statistics-read function entry."));
    UEdGraphPin* ReadMap = StatsMap(ReadGraph, Entry, Contract, Error);
    if (!ReadMap) return Fail(Error);
    UK2Node_CallFunction* Find = MapCall(ReadGraph, TEXT("Map_Find"), ReadMap, Contract, Error);
    if (!Find) return Fail(Error);
    UK2Node_FunctionResult* Result = AddNode<UK2Node_FunctionResult>(ReadGraph, [](UK2Node_FunctionResult* Node)
    {
        Node->FunctionReference.SetSelfMember(TEXT("CfReadConstructionStats"));
    });
    UEdGraphPin* FoundOutput = Result->CreateUserDefinedPin(TEXT("Found"), ScalarPin(UEdGraphSchema_K2::PC_Boolean), EGPD_Input);
    UEdGraphPin* SavedOutput = Result->CreateUserDefinedPin(TEXT("Saved"), StructPin(Contract.Collection->Struct), EGPD_Input);
    if (!Connect(ReadGraph, Entry->FindPin(UEdGraphSchema_K2::PN_Then), Result->FindPin(UEdGraphSchema_K2::PN_Execute), Error)
        || !Connect(ReadGraph, Find->GetReturnValuePin(), FoundOutput, Error)
        || !Connect(ReadGraph, Find->FindPin(TEXT("Value")), SavedOutput, Error)) return Fail(Error);

    Entry = nullptr;
    UEdGraph* RestoreGraph = AddFunction(Blueprint, TEXT("CfRestoreConstructionStats"), Entry);
    if (!Entry) return Fail(TEXT("Missing statistics-restore function entry."));
    UEdGraphPin* RestoreMap = StatsMap(RestoreGraph, Entry, Contract, Error);
    if (!RestoreMap) return Fail(Error);
    UEdGraphPin* FoundInput = Entry->CreateUserDefinedPin(TEXT("Found"), ScalarPin(UEdGraphSchema_K2::PC_Boolean), EGPD_Output);
    UEdGraphPin* SavedInput = Entry->CreateUserDefinedPin(TEXT("Saved"), StructPin(Contract.Collection->Struct), EGPD_Output);
    UK2Node_IfThenElse* Branch = AddNode<UK2Node_IfThenElse>(RestoreGraph, [](UK2Node_IfThenElse*) {});
    UK2Node_CallFunction* Add = MapCall(RestoreGraph, TEXT("Map_Add"), RestoreMap, Contract, Error);
    UK2Node_CallFunction* Remove = MapCall(RestoreGraph, TEXT("Map_Remove"), RestoreMap, Contract, Error);
    if (!Add || !Remove) return Fail(Error);
    if (!Connect(RestoreGraph, Entry->FindPin(UEdGraphSchema_K2::PN_Then), Branch->GetExecPin(), Error)
        || !Connect(RestoreGraph, FoundInput, Branch->GetConditionPin(), Error)
        || !Connect(RestoreGraph, Branch->GetThenPin(), Add->FindPin(UEdGraphSchema_K2::PN_Execute), Error)
        || !Connect(RestoreGraph, Branch->GetElsePin(), Remove->FindPin(UEdGraphSchema_K2::PN_Execute), Error)
        || !Connect(RestoreGraph, SavedInput, Add->FindPin(TEXT("Value")), Error)) return Fail(Error);

    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
    FCompilerResultsLog Results;
    FKismetEditorUtilities::CompileBlueprint(Blueprint, EBlueprintCompileOptions::SkipGarbageCollection, &Results);
    Report->SetNumberField(TEXT("compile_errors"), Results.NumErrors);
    Report->SetNumberField(TEXT("compile_warnings"), Results.NumWarnings);
    if (Results.NumErrors || !Blueprint->GeneratedClass || Blueprint->Status == BS_Error)
        return Fail(TEXT("Transient Blueprint did not compile; see editor compiler log."));

    UFunction* PrimaryFunction = Blueprint->GeneratedClass->FindFunctionByName(TEXT("CfSetPrimaryWarehouse"));
    UFunction* FuelFunction = Blueprint->GeneratedClass->FindFunctionByName(TEXT("CfSetBurnTime"));
    UFunction* GrantFunction = Blueprint->GeneratedClass->FindFunctionByName(TEXT("CfGrantWood"));
    UFunction* ReadFunction = Blueprint->GeneratedClass->FindFunctionByName(TEXT("CfReadConstructionStats"));
    UFunction* RestoreFunction = Blueprint->GeneratedClass->FindFunctionByName(TEXT("CfRestoreConstructionStats"));
    if (!PrimaryFunction || !FuelFunction || !GrantFunction || !ReadFunction || !RestoreFunction)
        return Fail(TEXT("Compiled bridge functions missing."));
    FBoolProperty* FoundResult = FindFProperty<FBoolProperty>(ReadFunction, TEXT("Found"));
    FStructProperty* SavedResult = FindFProperty<FStructProperty>(ReadFunction, TEXT("Saved"));
    FStructProperty* SavedParameter = FindFProperty<FStructProperty>(RestoreFunction, TEXT("Saved"));
    if (PrimaryFunction->NumParms != 2 || FuelFunction->NumParms != 2 || GrantFunction->NumParms != 3
        || ReadFunction->NumParms != 4 || RestoreFunction->NumParms != 4
        || !FoundResult || !FoundResult->HasAnyPropertyFlags(CPF_OutParm)
        || !SavedResult || !SavedResult->HasAnyPropertyFlags(CPF_OutParm) || SavedResult->Struct != Contract.Collection->Struct
        || !SavedParameter || SavedParameter->Struct != Contract.Collection->Struct
        || !FindFProperty<FIntProperty>(GrantFunction, TEXT("Count"))) return Fail(TEXT("Compiled bridge signatures differ from the requested contract."));
    const FString PrimaryCode = Disassemble(PrimaryFunction);
    const FString FuelCode = Disassemble(FuelFunction);
    const FString GrantCode = Disassemble(GrantFunction);
    const FString ReadCode = Disassemble(ReadFunction);
    const FString RestoreCode = Disassemble(RestoreFunction);
    Report->SetStringField(TEXT("primary_warehouse_bytecode"), PrimaryCode);
    Report->SetStringField(TEXT("burn_time_bytecode"), FuelCode);
    Report->SetStringField(TEXT("native_cdo_call_bytecode"), GrantCode);
    Report->SetStringField(TEXT("construction_stats_read_bytecode"), ReadCode);
    Report->SetStringField(TEXT("construction_stats_restore_bytecode"), RestoreCode);
    const bool bMemberOnly = PrimaryCode.Contains(TEXT("Let Obj (Variable = Expression)"))
        && PrimaryCode.Contains(TEXT("Member named primaryWarehouse"))
        && PrimaryCode.Contains(TEXT("named m_worldMeta."))
        && !PrimaryCode.Contains(TEXT("Let (Variable = Expression)"))
        && !PrimaryCode.Contains(TEXT("StructConst"));
    const bool bNativeCalls = GrantCode.Contains(TEXT("LoadCdoOfClass")) && GrantCode.Contains(TEXT("Arco_GiveResource"));
    const bool bStatsByRef = ReadCode.Contains(TEXT("Map_Find")) && RestoreCode.Contains(TEXT("Map_Add"))
        && RestoreCode.Contains(TEXT("Map_Remove")) && RestoreCode.Contains(TEXT("Array Get-by-Ref Index"))
        && RestoreCode.Contains(TEXT("Member named resourcesSummary")) && RestoreCode.Contains(TEXT("Member named m_resourceFlows"))
        && !RestoreCode.Contains(TEXT("Array_Set")) && !RestoreCode.Contains(TEXT("SetArray"));
    Report->SetBoolField(TEXT("primary_warehouse_member_only_no_struct_copy"), bMemberOnly);
    Report->SetBoolField(TEXT("original_native_calls_present"), bNativeCalls);
    Report->SetBoolField(TEXT("burn_time_property_present"), FuelCode.Contains(TEXT("named m_burnTimeRemaining.")));
    Report->SetBoolField(TEXT("construction_stats_map_by_reference"), bStatsByRef);
    Report->SetBoolField(TEXT("function_signatures_validated"), true);

    TSet<FString> ReferencePaths;
    TArray<TSharedPtr<FJsonValue>> References;
    bool bProbeRuntimeReference = false;
    for (UStruct* Struct : { static_cast<UStruct*>(Blueprint->GeneratedClass), static_cast<UStruct*>(PrimaryFunction),
        static_cast<UStruct*>(FuelFunction), static_cast<UStruct*>(GrantFunction), static_cast<UStruct*>(ReadFunction), static_cast<UStruct*>(RestoreFunction) })
    {
        for (const TObjectPtr<UObject>& Reference : Struct->ScriptAndPropertyObjectReferences)
        {
            if (!Reference) continue;
            const FString Path = Reference->GetPathName();
            ReferencePaths.Add(Path);
            bProbeRuntimeReference |= Path.StartsWith(TEXT("/Script/CampfireProbeEditor."));
        }
    }
    for (const FString& Path : ReferencePaths) References.Add(MakeShared<FJsonValueString>(Path));
    Report->SetArrayField(TEXT("compiled_object_references"), References);
    Report->SetBoolField(TEXT("probe_plugin_runtime_reference"), bProbeRuntimeReference);
    Report->SetBoolField(TEXT("success"), bMemberOnly && bNativeCalls
        && bStatsByRef && FuelCode.Contains(TEXT("named m_burnTimeRemaining.")) && !bProbeRuntimeReference);
    Report->SetStringField(TEXT("scope"), TEXT("Blueprint authoring and compilation only; no native action execution, save, cook, or installation."));
    return Json(Report);
}
