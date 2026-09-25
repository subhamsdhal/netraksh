# NETRAKSH: Elevator Pitch

## 30-Second Version
"Remote borders face two massive challenges: spotting intrusions and keeping data flowing when the network drops. NETRAKSH solves this by moving AI directly to the Edge. Instead of streaming heavy, raw video to the cloud, our cameras process frames locally, detecting threats like line-crossings and unauthorized vehicles. If the network drops, it buffers the data offline. When connectivity returns, it syncs those threats as cryptographically signed, tamper-evident evidence to a secure, role-based Command Center. It’s smart, offline-resilient, and cryptographically secure border surveillance."

## 60-Second Version
"Border security currently relies on passive CCTV cameras that require constant human monitoring and continuous high-bandwidth cloud streaming. When the network drops at a remote outpost, you lose both visibility and evidence. 

NETRAKSH transforms those passive cameras into an intelligent, Edge-to-Cloud platform. We run lightweight AI—like YOLO detection and object tracking—directly on the Edge node. This cuts bandwidth dependence, as we only transmit critical event metadata and evidence snapshots. 

Crucially, NETRAKSH is designed for austere environments. If the network goes down, the Edge node enters a store-and-forward mode, queuing events locally. Before any data leaves the Edge, it is hashed and cryptographically signed to guarantee the evidence hasn't been tampered with. 

On the backend, our Command Center routes these verified alerts strictly based on Command-Level permissions, ensuring operators only see what they are authorized to see. We provide a highly secure, offline-resilient, and intelligent surveillance pipeline."
