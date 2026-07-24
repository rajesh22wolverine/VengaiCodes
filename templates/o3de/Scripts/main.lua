----------------------------------------------------------------------------
-- VengaiCode O3DE template — minimal real Lua component script.
-- Structure (Properties table, OnActivate/OnDeactivate, `return Table`)
-- matches O3DE's own documented Lua script format and the real example
-- shipped in the engine's own AutomatedTesting/test1.lua — not invented.
----------------------------------------------------------------------------
local Main =
{
    Properties =
    {
        HeartbeatIntervalSeconds = { default = 5.0 },
    },
}

function Main:OnActivate()
    self.elapsed = 0.0
    self.tickBusHandler = TickBus.Connect(self)
    Debug.Log("VengaiCode O3DE template: Main activated")
end

function Main:OnTick(deltaTime, timePoint)
    self.elapsed = self.elapsed + deltaTime
    if self.elapsed >= self.Properties.HeartbeatIntervalSeconds then
        self.elapsed = 0.0
        Debug.Log("VengaiCode O3DE template: heartbeat")
    end
end

function Main:OnDeactivate()
    if self.tickBusHandler ~= nil then
        self.tickBusHandler:Disconnect()
        self.tickBusHandler = nil
    end
end

return Main
