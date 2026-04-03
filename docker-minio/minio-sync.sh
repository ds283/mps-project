mc alias set live-assets http://mps026298.phys.susx.ac.uk:8080 pG1SZIjSkRTojUx9yiVQw81n dNTBq04JG2k5As6pblBK9DIM
mc alias set live-backup http://mps026298.phys.susx.ac.uk:8080 BclpcqdIvwP4YOKs2HbP5yRn 7pweJ2gSIVjshP4LjcbAeAvR
mc alias set live-telemetry http://mps026298.phys.susx.ac.uk:8080 AuFZ5frNzBEDwoLPd4E2bUI7 TozXgTiW0kanWCtLr50vVjf3
mc alias set live-feedback http://mps026298.phys.susx.ac.uk:8080 iou2f8IL7mt2gKpsmmzIfNJz 5PBcWY1twkQM0rPQPXgZCxli
mc alias set live-project http://mps026298.phys.susx.ac.uk:8080 bvPPFPTVZXpdTSCmRW474u4G zj9CngU9HDrxhrd4ushbkF3q
mc alias set live-supervision-assets http://mps026298.phys.susx.ac.uk:8080 a6oTRRJlRvRD5Gc2zj0vqRje Np4IGsaiCsEWx6St0b7W5HRxMCnjHjcazCeYd0hU
mc alias set live-thumbnails http://mps026298.phys.susx.ac.uk:8080 86nb08heVOfIjOMsv6HnOXW6 foOGntngGd27wfLpWQDadDjQseShRVeWIlwnpwV6

mc alias set local http://localhost:9000 F9zwv1hqfBWL1b7X3fb3 5fNEDzU8EigE1Q02InGH4gkV0miB1AOSQ5tbnuT8

mc mirror live-assets/assets local/assets
mc mirror live-backup/backup local/backup
mc mirror live-telemetry/telemetry local/telemetry
mc mirror live-feedback/feedback local/feedback
mc mirror live-project/project local/project
mv mirror live-supervision-assets local/supervision-assets
mc mirror live-thumbnails local/thumbnails
