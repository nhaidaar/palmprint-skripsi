# PalmGate Access

## Language

**Entry camera**: The camera at the entrance, used for entry palm captures and enrollment.

**Exit camera**: The camera at the exit, used for exit palm captures.

**Access attempt**: A palm recognition attempt with an ALLOWED or DENIED decision. The decision does not prove that a person passed through the door.

**Direction**: ENTRY or EXIT, determined by the physical camera in normal operation or the selected camera role during debug testing. Historical and unlabeled attempts have no known direction.

**Debug input**: One browser camera assigned the Entry or Exit role for testing access attempts without actuating the door lock.

**Recognition model**: The single palm identity model shared by both cameras. Hand detection locates the palm before recognition.
