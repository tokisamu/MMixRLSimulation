// AnoRL mix network over Amigo mobility traces, in ns-3.
//
// The point of this simulator is to measure two things that a closed-form mixnet model
// cannot give for a mobile ad-hoc network: the delay a message actually accumulates when
// each hop between mixes has to cross a multi-hop wireless mesh whose topology is moving,
// and the arrival/departure times at each mix, from which the anonymity entropy is
// computed offline by analysis/entropy.py.
//
// The protocol simulated is the one of the paper.  A client originates a Sphinx packet for
// a random sequence of L mixes; every origination consumes one token of its originator for
// the current 60 s slot; a mix holds a packet for an exponentially distributed time and
// then originates it toward the next mix, spending a token of its own; the last mix
// broadcasts the payload.  Tokens are the rate limit, so a node whose budget for the slot
// is exhausted holds the packet until the next slot rather than dropping it.
//
// This file is self-contained and writes only into anorl-mixsim/.
//
// Build:  ./build.sh          (symlinks into $NS3_DIR/scratch and builds)
// Run:    see run_sweep.py

#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/mobility-module.h"
#include "ns3/wifi-module.h"
#include "ns3/packet-socket-address.h"
#include "ns3/packet-socket-helper.h"
#include "ns3/packet-socket-factory.h"
#include "ns3/propagation-module.h"

#include <fstream>
#include <sstream>
#include <iostream>
#include <vector>
#include <map>
#include <set>
#include <deque>
#include <queue>
#include <algorithm>
#include <cmath>
#include <cstring>

using namespace ns3;

NS_LOG_COMPONENT_DEFINE ("AnoRLMix");

// ---------------------------------------------------------------- scenario ----

struct Msg
{
  double t;
  uint32_t src;
  uint32_t mid;
  std::vector<uint32_t> path;
};

struct Scenario
{
  uint32_t n = 0;
  std::string model;
  uint32_t layers = 3;
  uint32_t warmup = 30;
  uint32_t duration = 300;
  uint32_t budgetClient = 10;
  uint32_t budgetMix = 2500;
  std::vector<uint32_t> mixes;
  std::set<uint32_t> mixSet;
  std::vector<uint32_t> adv;
  std::set<uint32_t> advSet;       // combined model: drops and, if a mix, floods
  std::set<uint32_t> dropSet;      // droppers: discard every honest message received
  std::set<uint32_t> cmixSet;      // corrupted mixes: refuse honest messages, flood
  std::set<uint32_t> anyAdv;       // union, for marking adversarial traffic
  std::vector<Msg> msgs;
};

static Scenario
LoadScenario (const std::string &path)
{
  Scenario sc;
  std::ifstream fh (path.c_str ());
  if (!fh)
    {
      NS_FATAL_ERROR ("cannot open scenario " << path);
    }
  std::string line;
  while (std::getline (fh, line))
    {
      std::istringstream is (line);
      std::string key;
      is >> key;
      if (key == "N")
        {
          is >> sc.n;
        }
      else if (key == "MODEL")
        {
          is >> sc.model;
        }
      else if (key == "LAYERS")
        {
          is >> sc.layers;
        }
      else if (key == "WARMUP")
        {
          is >> sc.warmup;
        }
      else if (key == "DURATION")
        {
          is >> sc.duration;
        }
      else if (key == "BUDGET_CLIENT")
        {
          is >> sc.budgetClient;
        }
      else if (key == "BUDGET_MIX")
        {
          is >> sc.budgetMix;
        }
      else if (key == "MIXES")
        {
          uint32_t v;
          while (is >> v)
            {
              sc.mixes.push_back (v);
              sc.mixSet.insert (v);
            }
        }
      else if (key == "ADV")
        {
          uint32_t v;
          while (is >> v)
            {
              sc.adv.push_back (v);
              sc.advSet.insert (v);
            }
        }
      else if (key == "DROPPER")
        {
          uint32_t v;
          while (is >> v)
            {
              sc.dropSet.insert (v);
            }
        }
      else if (key == "CMIX")
        {
          uint32_t v;
          while (is >> v)
            {
              sc.cmixSet.insert (v);
            }
        }
      else if (key == "MSG")
        {
          Msg m;
          is >> m.t >> m.src >> m.mid;
          uint32_t v;
          while (is >> v)
            {
              m.path.push_back (v);
            }
          sc.msgs.push_back (m);
        }
    }
  sc.anyAdv = sc.advSet;
  sc.anyAdv.insert (sc.dropSet.begin (), sc.dropSet.end ());
  sc.anyAdv.insert (sc.cmixSet.begin (), sc.cmixSet.end ());
  return sc;
}

// ---------------------------------------------------------------- wire format ----
//
// What travels on the air.  In the real protocol the next hop is inside the Sphinx
// header and only the addressed mix can read it; the simulator carries it in the clear
// because it has to route the packet, and the analysis never uses a field that a network
// observer could not obtain (it uses arrival and departure times only).

struct Wire
{
  uint32_t mid;        // message id
  uint32_t hop;        // 0 .. L-1 while travelling to path[hop]; L for the final broadcast
  uint32_t dst;        // node id of the mix this packet is addressed to (or n for broadcast)
  uint32_t origin;     // node that originated THIS transmission (client or mix)
  uint32_t ttl;        // dissemination hop limit
  uint32_t carry;      // store-carry-forward retries spent at the current holder
  uint32_t slot;       // the slot whose token was spent on this transmission
  uint32_t adv;        // the message was originated by an adversary
  double origT;        // time the client originated the message (for end-to-end delay)
};

// ---------------------------------------------------------------- simulator ----

class AnoRLSim
{
public:
  AnoRLSim (const Scenario &sc, double range, double mixDelay, uint32_t pktSize,
            std::string transport, uint32_t floodTtl, double stop, std::string outPath,
            uint32_t seed, double jitterMs, uint32_t slotLen, std::string mobFile,
            uint32_t maxCarry, double carryGap, double guard, double grace);
  void Run (void);

private:
  void SetupNodes (void);
  void ScheduleWorkload (void);

  // protocol
  void Originate (uint32_t node, Wire w);          // spend a token, then transmit
  void Transmit (uint32_t node, Wire w);           // put it on the air
  void Receive (Ptr<Socket> sock);
  void HandleArrival (uint32_t node, Wire w);      // this node is the addressed mix
  void ReleaseFromMix (uint32_t node, Wire w);     // mix delay expired
  void Rebroadcast (uint32_t node, Wire w);

  // helpers
  bool SpendToken (uint32_t node, double now);
  uint32_t SlotOf (double t) const { return static_cast<uint32_t> (t / m_slotLen); }
  bool InWindow (uint32_t slot, double t) const;
  uint32_t NextHopTowards (uint32_t from, uint32_t to);
  void BuildGraph (void);
  Vector Pos (uint32_t i) const;
  void Log (const std::string &s) { m_out << s << "\n"; }

public:
  void OnDroppedMpdu (std::string ctx, WifiMacDropReason reason, Ptr<const WifiMpdu> mpdu);
private:

  Scenario m_sc;
  double m_range, m_mixDelay, m_stop, m_jitterMs;
  uint32_t m_pktSize, m_floodTtl, m_seed, m_slotLen, m_maxCarry;
  double m_carryGap, m_guard, m_grace;
  std::string m_transport, m_outPath, m_mobFile;

  NodeContainer m_nodes;
  NetDeviceContainer m_devs;
  std::vector<Ptr<Socket>> m_socks;
  std::vector<Address> m_addrs;

  Ptr<UniformRandomVariable> m_uni;
  Ptr<ExponentialRandomVariable> m_exp;

  // per-node token accounting: tokens spent in the current slot
  std::vector<uint32_t> m_spent;
  std::vector<uint32_t> m_slot;
  // packets waiting for the next slot because the budget was exhausted
  std::vector<std::deque<Wire>> m_held;

  // duplicate suppression for flooding: (mid, hop) already rebroadcast here
  std::vector<std::set<uint64_t>> m_seen;

  // routing oracle, rebuilt once a second
  std::vector<std::vector<uint32_t>> m_adj;
  std::map<uint32_t, std::vector<uint32_t>> m_route;   // dst -> next hop from each node
  double m_graphTime = -1e9;

  std::ofstream m_out;

  // counters
  uint64_t m_tx = 0, m_rx = 0, m_orig = 0, m_deliv = 0, m_lostBudget = 0, m_dropTtl = 0;
  uint64_t m_arrivals = 0, m_departures = 0, m_noRoute = 0, m_sendFail = 0, m_carryGiveUp = 0;
  uint64_t m_macDrop = 0, m_macRecovered = 0, m_macQueue = 0, m_expired = 0, m_guardDefer = 0;
  uint64_t m_advDrop = 0, m_origAdv = 0, m_delivAdv = 0, m_cmixRefuse = 0;
};

AnoRLSim::AnoRLSim (const Scenario &sc, double range, double mixDelay, uint32_t pktSize,
                    std::string transport, uint32_t floodTtl, double stop,
                    std::string outPath, uint32_t seed, double jitterMs, uint32_t slotLen,
                    std::string mobFile, uint32_t maxCarry, double carryGap,
                    double guard, double grace)
  : m_sc (sc), m_range (range), m_mixDelay (mixDelay), m_stop (stop), m_jitterMs (jitterMs),
    m_pktSize (pktSize), m_floodTtl (floodTtl), m_seed (seed), m_slotLen (slotLen),
    m_maxCarry (maxCarry), m_carryGap (carryGap), m_guard (guard), m_grace (grace),
    m_transport (transport), m_outPath (outPath), m_mobFile (mobFile)
{
}

Vector
AnoRLSim::Pos (uint32_t i) const
{
  return m_nodes.Get (i)->GetObject<MobilityModel> ()->GetPosition ();
}

void
AnoRLSim::BuildGraph (void)
{
  double now = Simulator::Now ().GetSeconds ();
  if (now - m_graphTime < 1.0)
    {
      return;
    }
  m_graphTime = now;
  uint32_t n = m_sc.n;
  m_adj.assign (n, {});
  std::vector<Vector> p (n);
  for (uint32_t i = 0; i < n; ++i)
    {
      p[i] = Pos (i);
    }
  for (uint32_t i = 0; i < n; ++i)
    {
      for (uint32_t j = i + 1; j < n; ++j)
        {
          double dx = p[i].x - p[j].x, dy = p[i].y - p[j].y;
          if (dx * dx + dy * dy <= m_range * m_range)
            {
              m_adj[i].push_back (j);
              m_adj[j].push_back (i);
            }
        }
    }

  // One backward breadth-first search per mix, so a transmission costs a table lookup
  // rather than a search.  Destinations are only the mixes.
  m_route.clear ();
  for (uint32_t dst : m_sc.mixes)
    {
      std::vector<uint32_t> nh (n, n);
      std::vector<char> vis (n, 0);
      std::queue<uint32_t> q;
      q.push (dst);
      vis[dst] = 1;
      nh[dst] = dst;
      while (!q.empty ())
        {
          uint32_t u = q.front ();
          q.pop ();
          for (uint32_t v : m_adj[u])
            {
              if (!vis[v])
                {
                  vis[v] = 1;
                  nh[v] = u;
                  q.push (v);
                }
            }
        }
      m_route[dst] = nh;
    }
}

uint32_t
AnoRLSim::NextHopTowards (uint32_t from, uint32_t to)
{
  // Breadth-first search on the current radio graph.  This is an oracle: it gives the
  // dissemination layer perfect neighbour knowledge, which is the paper's position that
  // how retransmission is organised is orthogonal to the token layer.  The MAC, the
  // contention and the losses are still ns-3's.
  BuildGraph ();
  if (from == to)
    {
      return to;
    }
  auto it = m_route.find (to);
  if (it == m_route.end ())
    {
      return m_sc.n;
    }
  return it->second[from];         // n if unreachable this second
}

void
AnoRLSim::SetupNodes (void)
{
  uint32_t n = m_sc.n;
  m_nodes.Create (n);

  Ns2MobilityHelper ns2 (m_mobFile);
  ns2.Install ();

  YansWifiChannelHelper chan;
  chan.SetPropagationDelay ("ns3::ConstantSpeedPropagationDelayModel");
  chan.AddPropagationLoss ("ns3::RangePropagationLossModel", "MaxRange", DoubleValue (m_range));
  YansWifiPhyHelper phy;
  phy.SetChannel (chan.Create ());

  WifiHelper wifi;
  wifi.SetStandard (WIFI_STANDARD_80211n);
  wifi.SetRemoteStationManager ("ns3::ConstantRateWifiManager",
                                "DataMode", StringValue ("HtMcs7"),
                                "ControlMode", StringValue ("HtMcs0"));
  WifiMacHelper mac;
  mac.SetType ("ns3::AdhocWifiMac");
  phy.Set ("ChannelSettings", StringValue ("{0, 40, BAND_5GHZ, 0}"));
  m_devs = wifi.Install (phy, mac, m_nodes);

  Config::SetFailSafe ("/NodeList/*/DeviceList/*/$ns3::WifiNetDevice/Mac/"
                       "Txop/Queue/MaxSize", QueueSizeValue (QueueSize ("512p")));

  PacketSocketHelper psh;
  psh.Install (m_nodes);

  m_socks.resize (n);
  m_addrs.resize (n);
  for (uint32_t i = 0; i < n; ++i)
    {
      Ptr<Socket> s = Socket::CreateSocket (m_nodes.Get (i),
                                            PacketSocketFactory::GetTypeId ());
      PacketSocketAddress local;
      local.SetSingleDevice (m_devs.Get (i)->GetIfIndex ());
      local.SetProtocol (7);
      s->Bind (local);
      s->SetRecvCallback (MakeCallback (&AnoRLSim::Receive, this));
      m_socks[i] = s;
      m_addrs[i] = m_devs.Get (i)->GetAddress ();
    }

  uint32_t mtu = m_devs.Get (0)->GetMtu ();
  if (m_pktSize > mtu)
    {
      std::cerr << "packet size " << m_pktSize << " exceeds the device MTU " << mtu
                << "; clamping" << std::endl;
      m_pktSize = mtu;
    }

  Config::Connect ("/NodeList/*/DeviceList/*/$ns3::WifiNetDevice/Mac/DroppedMpdu",
                   MakeCallback (&AnoRLSim::OnDroppedMpdu, this));

  m_spent.assign (n, 0);
  m_slot.assign (n, 0);
  m_held.resize (n);
  m_seen.resize (n);
}

bool
AnoRLSim::SpendToken (uint32_t node, double now)
{
  uint32_t slot = static_cast<uint32_t> (now / m_slotLen);
  if (m_slot[node] != slot)
    {
      m_slot[node] = slot;
      m_spent[node] = 0;
    }
  uint32_t budget = m_sc.mixSet.count (node) ? m_sc.budgetMix : m_sc.budgetClient;
  if (m_spent[node] >= budget)
    {
      return false;
    }
  m_spent[node]++;
  return true;
}

// Slots are fixed windows on the shared clock.  A spend is valid only inside the slot it
// was made in, so one made a second into a slot and one made a second before it ends both
// expire at the same boundary, with 59 s and 1 s of life respectively.  A packet past that
// point can no longer be verified by anyone, so every honest device drops it rather than
// carrying or relaying it further, which is what bounds store-carry-forward.
//
// m_grace and m_guard are off by default and exist only so the two variants that were
// tried can be reproduced: m_grace extends a spend's validity past the end of its slot,
// and m_guard stops anyone originating in the last seconds of one.
bool
AnoRLSim::InWindow (uint32_t slot, double t) const
{
  double start = static_cast<double> (slot) * m_slotLen;
  return t >= start && t < start + m_slotLen + m_grace;
}

void
AnoRLSim::Originate (uint32_t node, Wire w)
{
  double now = Simulator::Now ().GetSeconds ();

  // A token spent in the last moments of its slot has almost no life left, and on a
  // partitioned mesh a leg that short rarely completes.  A participant therefore does
  // not originate inside the guard band at the end of a slot; it waits for the next slot
  // and spends a token from that slot instead, so the budget is untouched.
  if (m_guard > 0.0)
    {
      double intoSlot = now - std::floor (now / m_slotLen) * m_slotLen;
      if (intoSlot >= m_slotLen - m_guard)
        {
          m_guardDefer++;
          double nextSlot = (std::floor (now / m_slotLen) + 1) * m_slotLen
                            + m_uni->GetValue (0.0, 1.0);
          if (nextSlot < m_stop)
            {
              Simulator::Schedule (Seconds (nextSlot - now), &AnoRLSim::Originate,
                                   this, node, w);
            }
          return;
        }
    }

  if (!SpendToken (node, now))
    {
      // Budget exhausted for this slot: hold the packet until the next slot rather than
      // drop it (the paper's rule).  Re-try at the next slot boundary.
      m_lostBudget++;
      // stagger the retry, so that a slot boundary is not a synchronised burst
      double nextSlot = (std::floor (now / m_slotLen) + 1) * m_slotLen
                        + m_uni->GetValue (0.0, 1.0);
      if (nextSlot < m_stop)
        {
          Simulator::Schedule (Seconds (nextSlot - now), &AnoRLSim::Originate, this, node, w);
        }
      return;
    }
  w.slot = SlotOf (now);          // the token just spent belongs to this slot
  w.carry = 0;
  m_orig++;
  if (w.adv)
    {
      m_origAdv++;
    }
  std::ostringstream os;
  os << "ORIG " << w.mid << " " << std::fixed << now << " " << node << " " << w.hop
     << " " << w.dst;
  Log (os.str ());
  Transmit (node, w);
}

void
AnoRLSim::Transmit (uint32_t node, Wire w)
{
  Ptr<Packet> pkt = Create<Packet> (reinterpret_cast<const uint8_t *> (&w), sizeof (Wire));
  if (m_pktSize > sizeof (Wire))
    {
      pkt->AddPaddingAtEnd (m_pktSize - sizeof (Wire));
    }

  PacketSocketAddress dest;
  dest.SetSingleDevice (m_devs.Get (node)->GetIfIndex ());
  dest.SetProtocol (7);

  if (m_transport == "flood" || w.dst >= m_sc.n)
    {
      dest.SetPhysicalAddress (m_devs.Get (node)->GetBroadcast ());
    }
  else
    {
      uint32_t nh = NextHopTowards (node, w.dst);
      if (nh >= m_sc.n)
        {
          // No path to the addressed mix at this instant.  A node under mobility holds
          // the packet and retries rather than dropping it; the hold is capped so that a
          // packet cannot outlive the slot window that its token belongs to.
          m_noRoute++;
          double retryAt = Simulator::Now ().GetSeconds () + m_carryGap;
          if (!InWindow (w.slot, retryAt))
            {
              m_expired++;        // the token would no longer verify: drop, do not carry
            }
          else if (w.carry < m_maxCarry && retryAt < m_stop)
            {
              Wire c = w;
              c.carry++;
              Simulator::Schedule (Seconds (m_carryGap), &AnoRLSim::Transmit, this, node, c);
            }
          else
            {
              m_carryGiveUp++;
            }
          return;
        }
      dest.SetPhysicalAddress (m_addrs[nh]);
    }
  m_tx++;
  int rc = m_socks[node]->SendTo (pkt, 0, dest);
  if (rc < 0)
    {
      m_sendFail++;
    }
}

static uint32_t
NodeIdFromContext (const std::string &ctx)
{
  // "/NodeList/<id>/DeviceList/..."
  size_t a = ctx.find ("/NodeList/");
  if (a == std::string::npos)
    {
      return UINT32_MAX;
    }
  a += 10;
  size_t b = ctx.find ('/', a);
  return static_cast<uint32_t> (std::stoul (ctx.substr (a, b - a)));
}

void
AnoRLSim::OnDroppedMpdu (std::string ctx, WifiMacDropReason reason,
                          Ptr<const WifiMpdu> mpdu)
{
  m_macDrop++;
  if (reason == WIFI_MAC_DROP_FAILED_ENQUEUE)
    {
      m_macQueue++;
      return;
    }
  uint32_t node = NodeIdFromContext (ctx);
  if (node >= m_sc.n || Simulator::Now ().GetSeconds () >= m_stop)
    {
      return;
    }
  Ptr<const Packet> p = mpdu->GetPacket ();
  uint32_t sz = p->GetSize ();
  if (sz < m_pktSize)
    {
      return;
    }
  std::vector<uint8_t> buf (sz);
  p->CopyData (buf.data (), sz);
  uint32_t off = sz - m_pktSize;                 // skip the LLC/SNAP header
  if (off + sizeof (Wire) > sz)
    {
      return;
    }
  Wire w;
  std::memcpy (&w, buf.data () + off, sizeof (Wire));
  if (w.mid >= m_sc.msgs.size () || w.hop > m_sc.layers || w.dst > m_sc.n)
    {
      return;                                    // not one of ours
    }
  if (w.ttl == 0 || w.dst >= m_sc.n)
    {
      return;                // a broadcast is not retried
    }
  if (!InWindow (w.slot, Simulator::Now ().GetSeconds ()))
    {
      m_expired++;
      return;
    }
  m_macRecovered++;
  w.ttl--;
  // the routing table is rebuilt every simulated second, so a short pause lets the
  // sender pick a next hop that is actually in range
  Simulator::Schedule (MilliSeconds (m_uni->GetInteger (20, 200)), &AnoRLSim::Transmit,
                       this, node, w);
}

void
AnoRLSim::Receive (Ptr<Socket> sock)
{
  Ptr<Packet> pkt;
  Address from;
  while ((pkt = sock->RecvFrom (from)))
    {
      m_rx++;
      uint32_t node = sock->GetNode ()->GetId ();
      Wire w;
      if (pkt->GetSize () < sizeof (Wire))
        {
          continue;
        }
      pkt->CopyData (reinterpret_cast<uint8_t *> (&w), sizeof (Wire));

      if (!InWindow (w.slot, Simulator::Now ().GetSeconds ()))
        {
          m_expired++;            // outside the acceptance window: no verification, drop
          continue;
        }

      // A dropper discards every honest message it receives, whether it was asked to relay
      // it or addressed as its mix.  The combined model of the earlier experiment behaves
      // the same way.  Adversarial traffic is always carried, since that is how an
      // adversary spends its budget.
      if (w.adv == 0 && (m_sc.advSet.count (node) || m_sc.dropSet.count (node)))
        {
          m_advDrop++;
          continue;
        }
      // A corrupted mix refuses to mix any honest message addressed to it, but relays
      // honest traffic addressed elsewhere like any other node.  Its attack is the flood it
      // originates, not blackholing, so that the two effects can be measured separately.
      if (w.adv == 0 && w.dst == node && m_sc.cmixSet.count (node))
        {
          m_cmixRefuse++;
          continue;
        }

      if (w.dst == node)
        {
          uint64_t key = (static_cast<uint64_t> (w.mid) << 8) | w.hop;
          if (m_seen[node].count (key))
            {
              continue;               // already being held or already forwarded
            }
          m_seen[node].insert (key);
          HandleArrival (node, w);
        }
      else if (w.dst >= m_sc.n)
        {
          // final broadcast: everyone in range receives the payload
          uint64_t key = (static_cast<uint64_t> (w.mid) << 8) | 0xFF;
          if (m_seen[node].count (key))
            {
              continue;
            }
          m_seen[node].insert (key);
          if (m_transport == "flood" && w.ttl > 0)
            {
              Rebroadcast (node, w);
            }
        }
      else if (m_transport == "flood")
        {
          uint64_t key = (static_cast<uint64_t> (w.mid) << 8) | w.hop;
          if (m_seen[node].count (key))
            {
              continue;
            }
          m_seen[node].insert (key);
          if (w.ttl > 0)
            {
              Rebroadcast (node, w);
            }
          else
            {
              m_dropTtl++;
            }
        }
      else
        {
          // unicast relay toward the addressed mix; relaying costs no token
          if (w.ttl > 0)
            {
              w.ttl--;
              Transmit (node, w);
            }
          else
            {
              m_dropTtl++;
            }
        }
    }
}

void
AnoRLSim::Rebroadcast (uint32_t node, Wire w)
{
  w.ttl--;
  double j = m_uni->GetValue (5.0, m_jitterMs) / 1000.0;
  Simulator::Schedule (Seconds (j), &AnoRLSim::Transmit, this, node, w);
}

void
AnoRLSim::HandleArrival (uint32_t node, Wire w)
{
  double now = Simulator::Now ().GetSeconds ();
  m_arrivals++;
  std::ostringstream os;
  os << "ARR " << w.mid << " " << std::fixed << now << " " << node << " " << w.hop;
  Log (os.str ());
  double d = m_exp->GetValue ();
  Simulator::Schedule (Seconds (d), &AnoRLSim::ReleaseFromMix, this, node, w);
}

void
AnoRLSim::ReleaseFromMix (uint32_t node, Wire w)
{
  double now = Simulator::Now ().GetSeconds ();
  if (now >= m_stop)
    {
      return;
    }
  m_departures++;
  std::ostringstream os;
  os << "DEP " << w.mid << " " << std::fixed << now << " " << node << " " << w.hop;
  Log (os.str ());

  Wire nw = w;
  nw.hop = w.hop + 1;
  nw.origin = node;
  nw.ttl = m_floodTtl;
  nw.carry = 0;
  if (nw.hop >= m_sc.layers)
    {
      nw.dst = m_sc.n;               // final broadcast
      std::ostringstream o2;
      o2 << "DELIV " << w.mid << " " << std::fixed << now << " " << node
         << " " << (now - w.origT);
      Log (o2.str ());
      m_deliv++;
      if (w.adv)
        {
          m_delivAdv++;
        }
    }
  else
    {
      // the next mix on the path; the simulator looks it up from the scenario
      nw.dst = m_sc.msgs[w.mid].path[nw.hop];
    }
  Originate (node, nw);
}

void
AnoRLSim::ScheduleWorkload (void)
{
  for (const Msg &m : m_sc.msgs)
    {
      if (m.t >= m_stop)
        {
          continue;
        }
      Wire w;
      w.mid = m.mid;
      w.hop = 0;
      w.dst = m.path[0];
      w.origin = m.src;
      w.ttl = m_floodTtl;
      w.carry = 0;
      w.origT = m.t;
      w.adv = m_sc.anyAdv.count (m.src) ? 1 : 0;
      Simulator::Schedule (Seconds (m.t), &AnoRLSim::Originate, this, m.src, w);
    }
}

void
AnoRLSim::Run (void)
{
  RngSeedManager::SetSeed (m_seed);
  RngSeedManager::SetRun (1);
  m_uni = CreateObject<UniformRandomVariable> ();
  m_exp = CreateObject<ExponentialRandomVariable> ();
  m_exp->SetAttribute ("Mean", DoubleValue (m_mixDelay));

  SetupNodes ();

  m_out.open (m_outPath.c_str ());
  if (!m_out)
    {
      NS_FATAL_ERROR ("cannot write " << m_outPath);
    }
  m_out << "# anorl-mix event log\n";
  m_out << "# PARAM layers " << m_sc.layers << " mixdelay " << m_mixDelay
        << " transport " << m_transport << " pktsize " << m_pktSize
        << " range " << m_range << " stop " << m_stop
        << " slot " << m_slotLen << " grace " << m_grace << " guard " << m_guard
        << " budget_client " << m_sc.budgetClient << " budget_mix " << m_sc.budgetMix
        << " n " << m_sc.n << " n_mix " << m_sc.mixes.size () << "\n";
  if (!m_sc.anyAdv.empty ())
    {
      m_out << "# ADV";
      for (uint32_t x : m_sc.anyAdv)
        {
          m_out << " " << x;
        }
      m_out << "\n";
    }
  if (!m_sc.dropSet.empty ())
    {
      m_out << "# DROPPER";
      for (uint32_t x : m_sc.dropSet)
        {
          m_out << " " << x;
        }
      m_out << "\n";
    }
  if (!m_sc.cmixSet.empty ())
    {
      m_out << "# CMIX";
      for (uint32_t x : m_sc.cmixSet)
        {
          m_out << " " << x;
        }
      m_out << "\n";
    }
  m_out << "# MIXES";
  for (uint32_t x : m_sc.mixes)
    {
      m_out << " " << x;
    }
  m_out << "\n";

  ScheduleWorkload ();
  Simulator::Stop (Seconds (m_stop));
  Simulator::Run ();
  Simulator::Destroy ();

  m_out << "# STATS originations " << m_orig << " tx " << m_tx << " rx " << m_rx
        << " arrivals " << m_arrivals << " departures " << m_departures
        << " delivered " << m_deliv << " budget_deferred " << m_lostBudget
        << " ttl_drop " << m_dropTtl << " no_route " << m_noRoute
        << " send_fail " << m_sendFail
        << " carry_retries " << m_noRoute << " carry_giveup " << m_carryGiveUp
        << " mac_drop " << m_macDrop
        << " mac_recovered " << m_macRecovered << " mac_queue " << m_macQueue
        << " expired " << m_expired
        << " guard_defer " << m_guardDefer
        << " adv_drop " << m_advDrop
        << " orig_adv " << m_origAdv << " delivered_adv " << m_delivAdv
        << " cmix_refuse " << m_cmixRefuse << "\n";
  m_out.close ();

  std::cout << "originations=" << m_orig << " tx=" << m_tx << " rx=" << m_rx
            << " arrivals=" << m_arrivals << " departures=" << m_departures
            << " delivered=" << m_deliv << " deferred=" << m_lostBudget
            << " ttl_drop=" << m_dropTtl << " no_route=" << m_noRoute
            << " send_fail=" << m_sendFail
            << " carry_giveup=" << m_carryGiveUp << " mac_drop=" << m_macDrop
            << " mac_recovered=" << m_macRecovered << " mac_queue=" << m_macQueue
            << " expired=" << m_expired
            << " guard_defer=" << m_guardDefer << " adv_drop=" << m_advDrop
            << " orig_adv=" << m_origAdv << " deliv_adv=" << m_delivAdv
            << " cmix_refuse=" << m_cmixRefuse << std::endl;
}

// ---------------------------------------------------------------- main ----

int
main (int argc, char *argv[])
{
  std::string scn, mob, out = "events.log", transport = "route";
  double range = 10.0, mixDelay = 5.0, stop = 0.0, jitterMs = 40.0, guard = 0.0,
         grace = 0.0;
  uint32_t pktSize = 1024, floodTtl = 96, seed = 1, slotLen = 60, maxCarry = 20;
  double carryGap = 1.0;

  CommandLine cmd;
  cmd.AddValue ("scn", "scenario file", scn);
  cmd.AddValue ("mob", "ns-2 mobility trace", mob);
  cmd.AddValue ("out", "event log output path", out);
  cmd.AddValue ("transport", "flood | route", transport);
  cmd.AddValue ("range", "radio range in metres", range);
  cmd.AddValue ("mixdelay", "mean of the exponential mix delay, seconds", mixDelay);
  cmd.AddValue ("pktsize", "bytes on the air per packet", pktSize);
  cmd.AddValue ("floodttl", "dissemination hop limit", floodTtl);
  cmd.AddValue ("stop", "simulated seconds (0 = warmup+duration from the scenario)", stop);
  cmd.AddValue ("seed", "RNG seed", seed);
  cmd.AddValue ("slot", "token slot length in seconds", slotLen);
  cmd.AddValue ("jitter", "max rebroadcast jitter in ms", jitterMs);
  cmd.AddValue ("carry", "store-carry-forward retries when no route exists", maxCarry);
  cmd.AddValue ("carrygap", "seconds between store-carry-forward retries", carryGap);
  cmd.AddValue ("guard", "seconds at the end of a slot in which nobody originates", guard);
  cmd.AddValue ("grace", "seconds a spend stays valid past the end of its own slot", grace);
  cmd.Parse (argc, argv);

  if (scn.empty () || mob.empty ())
    {
      std::cerr << "need --scn and --mob" << std::endl;
      return 1;
    }
  Scenario sc = LoadScenario (scn);
  if (stop <= 0.0)
    {
      stop = sc.warmup + sc.duration;
    }
  std::cout << "scenario n=" << sc.n << " mixes=" << sc.mixes.size ()
            << " layers=" << sc.layers << " messages=" << sc.msgs.size ()
            << " stop=" << stop << "s transport=" << transport << std::endl;

  AnoRLSim sim (sc, range, mixDelay, pktSize, transport, floodTtl, stop, out, seed,
                jitterMs, slotLen, mob, maxCarry, carryGap, guard, grace);
  sim.Run ();
  return 0;
}
