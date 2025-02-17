import unittest, unittest.mock, os, io, itertools, gzip, json
import botocore.exceptions
from .. import observe, data

should_gzip = itertools.cycle([True, False])

def mock_s3_get_object(Bucket, Key):
    '''
    '''
    path = os.path.join(os.path.dirname(__file__), 'data', Key)
    if not os.path.exists(path):
        raise botocore.exceptions.ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
    with open(path, 'rb') as file:
        if next(should_gzip):
            return {'Body': io.BytesIO(gzip.compress(file.read())),
                'ContentEncoding': 'gzip'}
        else:
            return {'Body': io.BytesIO(file.read())}

class TestObserveTiles (unittest.TestCase):

    def test_get_upload_index(self):
        ''' Upload index file is retrieved from S3
        '''
        storage, key = unittest.mock.Mock(), 'fake-key'
        
        body = unittest.mock.Mock()
        body.read.return_value = '{"id": "fake-id", "key": "fake-key"}'
        storage.s3.get_object.return_value = {'Body': body}
        
        result = observe.get_upload_index(storage, key)

        get_call = storage.s3.get_object.mock_calls[0]
        
        self.assertEqual(get_call[2], dict(Bucket=storage.bucket, Key=key))
        self.assertEqual(result.id, 'fake-id')
    
    def test_put_upload_index(self):
        ''' Upload index file is posted to S3
        '''
        storage, upload = unittest.mock.Mock(), unittest.mock.Mock()
        observe.put_upload_index(storage, upload)
        
        put_call1, put_call2, put_call3 = storage.s3.put_object.mock_calls
        
        self.assertEqual(put_call1[2], dict(Bucket=storage.bucket,
            Key=upload.index_key.return_value,
            Body=upload.to_json.return_value.encode.return_value,
            CacheControl='public, no-cache, no-store',
            ACL='public-read', ContentType='text/json'))
        
        self.assertEqual(put_call2[2], dict(Bucket=storage.bucket,
            Key=upload.plaintext_key.return_value,
            Body=upload.to_plaintext.return_value.encode.return_value,
            CacheControl='public, no-cache, no-store',
            ACL='public-read', ContentType='text/plain'))
        
        self.assertEqual(put_call3[2], dict(Bucket=storage.bucket,
            Key=upload.logentry_key.return_value,
            Body=upload.to_logentry.return_value.encode.return_value,
            CacheControl='public, no-cache, no-store',
            ACL='public-read', ContentType='text/plain'))

    def test_put_part_timings(self):
        ''' Upload timing file is posted to S3
        '''
        storage, upload = unittest.mock.Mock(), unittest.mock.Mock()
        upload.id, upload.start_time = 'fake-id', 1621099219
        upload.model = None
        observe.put_part_timings(storage, upload, [
            observe.SubTotal(None, dict(start_time=1.1, elapsed_time=2.2, features=3)),
            observe.SubTotal(None, dict(start_time=4.4, elapsed_time=5.5, features=6)),
        ], 'mock')
        
        (put_call, ) = storage.s3.put_object.mock_calls
        
        self.assertEqual(put_call[2], dict(Bucket=storage.bucket,
            Key=data.UPLOAD_TIMING_KEY.format(id=upload.id, ds='2021-05-15'),
            Body='fake-id\tmock\t3\t1.1\t2.2\t\t\t\r\nfake-id\tmock\t6\t4.4\t5.5\t\t\t\r\n',
            ACL='public-read', ContentType='text/plain'))

    def test_expected_tile(self):
        ''' Expected tile is returned for an enqueued one.
        '''
        upload = unittest.mock.Mock()
        upload.model.key_prefix = 'data/XX'
        upload.id = 'ID'
        
        enqueued_key1 = 'data/XX/12/656/1582.geojson'
        expected_key1 = 'uploads/ID/tiles/12/656/1582.json'
        
        self.assertEqual(observe.get_expected_tile(enqueued_key1, upload), expected_key1)
        
        enqueued_key2 = 'data/XX/tiles/12/656/1582.geojson'
        expected_key2 = 'uploads/ID/tiles/12/656/1582.json'
        
        self.assertEqual(observe.get_expected_tile(enqueued_key2, upload), expected_key2)
    
    def test_expected_slice(self):
        ''' Expected slice is returned for an enqueued one.
        '''
        upload = unittest.mock.Mock()
        upload.model.key_prefix = 'data/XX'
        upload.id = 'ID'
        
        enqueued_key = 'data/XX/slices/0000001.json'
        expected_key = 'uploads/ID/slices/0000001.json'
        
        self.assertEqual(observe.get_expected_slice(enqueued_key, upload), expected_key)
    
    def test_get_district_index(self):
        '''
        '''
        upload = unittest.mock.Mock()
        upload.id = 'ID'

        self.assertEqual(observe.get_district_index('uploads/ID/geometries/0.wkt', upload), 0)
        self.assertEqual(observe.get_district_index('uploads/ID/geometries/09.wkt', upload), 9)
        self.assertEqual(observe.get_district_index('uploads/ID/geometries/11.wkt', upload), 11)
        
        with self.assertRaises(ValueError):
            observe.get_district_index('uploads/ID/geometries/xx.wkt', upload)
        
        self.assertEqual(observe.get_district_index('uploads/ID/assignments/0.txt', upload), 0)
        self.assertEqual(observe.get_district_index('uploads/ID/assignments/09.txt', upload), 9)
        self.assertEqual(observe.get_district_index('uploads/ID/assignments/11.txt', upload), 11)

        with self.assertRaises(ValueError):
            observe.get_district_index('uploads/ID/assignments/xx.txt', upload)
    
    def test_load_upload_geometries(self):
        ''' Expected geometries are retrieved from S3.
        '''
        s3, upload = unittest.mock.Mock(), unittest.mock.Mock()
        storage = data.Storage(s3, 'bucket-name', 'XX')
        upload.id = 'sample-plan'

        s3.get_object.side_effect = mock_s3_get_object
        s3.list_objects.return_value = {'Contents': [
            {'Key': "uploads/sample-plan/geometries/0.wkt"},
            {'Key': "uploads/sample-plan/geometries/1.wkt"}
            ]}

        geometries = observe.load_upload_geometries(storage, upload)

        self.assertIs(type(geometries), list)
        self.assertEqual(len(geometries), 2)
        
        s3.list_objects.assert_called_once_with(Bucket='bucket-name',
            Prefix="uploads/sample-plan/geometries/")
    
    def test_load_upload_assignment_keys(self):
        ''' Expected assignment keys are retrieved from S3.
        '''
        s3, upload = unittest.mock.Mock(), unittest.mock.Mock()
        storage = data.Storage(s3, 'bucket-name', 'XX')
        upload.id = 'sample-plan3'

        s3.get_object.side_effect = mock_s3_get_object
        s3.list_objects.return_value = {'Contents': [
            {'Key': "uploads/sample-plan3/assignments/0.txt"},
            {'Key': "uploads/sample-plan3/assignments/1.txt"}
            ]}

        assignment_keys = observe.load_upload_assignment_keys(storage, upload)

        self.assertIs(type(assignment_keys), list)
        self.assertEqual(len(assignment_keys), 2)
        
        s3.list_objects.assert_called_once_with(Bucket='bucket-name',
            Prefix="uploads/sample-plan3/assignments/")

    @unittest.mock.patch('planscore.compactness.get_scores')
    def test_populate_compactness(self, get_scores):
        '''
        '''
        geometries = [unittest.mock.Mock()]
        districts = observe.populate_compactness(geometries)
        
        get_scores.assert_called_once_with(geometries[0])
        self.assertEqual(len(districts), len(geometries))
        self.assertEqual(districts[0]['compactness'], get_scores.return_value)
    
    @unittest.mock.patch('planscore.observe.wait_for_object')
    def test_build_blockassign_geojson(self, wait_for_object):
        '''
        '''
        context, storage = unittest.mock.Mock(), unittest.mock.Mock()
        lam, model = unittest.mock.Mock(), unittest.mock.Mock()
        model.state.value = 'XX'
        
        storage.to_event.return_value = {}
        
        wait_for_object.return_value = {'Body': unittest.mock.Mock()}
        wait_for_object.return_value['Body'].read.return_value = b'POINT(0 0)'
        
        district_keys = [
            (
                data.UPLOAD_ASSIGNMENTS_KEY.format(id='sample-plan3', index='0'),
                data.UPLOAD_GEOMETRIES_KEY.format(id='sample-plan3', index='0'),
            ),
            (
                data.UPLOAD_ASSIGNMENTS_KEY.format(id='sample-plan3', index='1'),
                data.UPLOAD_GEOMETRIES_KEY.format(id='sample-plan3', index='1'),
            )
        ]
        
        geojson = observe.build_blockassign_geojson(district_keys, model, storage, lam, context)
        self.assertTrue(geojson.startswith('{'))
        
        self.assertEqual(len(lam.invoke.mock_calls), 2)
        self.assertEqual(
            lam.invoke.mock_calls[0][2]['Payload'],
            '{"storage": {}, "assignment_key": "uploads/sample-plan3/assignments/0.txt", "geometry_key": "uploads/sample-plan3/geometries/0.wkt", "state_code": "XX"}',
        )
        self.assertEqual(
            lam.invoke.mock_calls[1][2]['Payload'],
            '{"storage": {}, "assignment_key": "uploads/sample-plan3/assignments/1.txt", "geometry_key": "uploads/sample-plan3/geometries/1.wkt", "state_code": "XX"}',
        )

    @unittest.mock.patch('planscore.observe.build_blockassign_geojson')
    @unittest.mock.patch('planscore.observe.load_upload_assignment_keys')
    @unittest.mock.patch('planscore.observe.put_upload_index')
    def test_add_blockassign_upload_geometry(self, put_upload_index, load_upload_assignment_keys, build_blockassign_geojson):
        context = unittest.mock.Mock()
        lam = unittest.mock.Mock()
        storage = unittest.mock.Mock()
        upload = unittest.mock.Mock()
        upload.id = 'sample-plan'
        load_upload_assignment_keys.return_value = [
            'uploads/sample-plan/assignments/0.txt',
            'uploads/sample-plan/assignments/1.txt',
        ]
        build_blockassign_geojson.return_value = '{"type": "FeatureCollection"}'
        
        observe.add_blockassign_upload_geometry(context, lam, storage, upload)
        
        build_blockassign_geojson.assert_called_once_with(
            [
                ('uploads/sample-plan/assignments/0.txt', 'uploads/sample-plan/geometries/0.wkt'),
                ('uploads/sample-plan/assignments/1.txt', 'uploads/sample-plan/geometries/1.wkt'),
            ],
            upload.model, storage, lam, context,
        )
        self.assertEqual(len(storage.s3.put_object.mock_calls), 1)
        self.assertEqual(storage.s3.put_object.mock_calls[0][2]['Bucket'], storage.bucket)
        self.assertEqual(storage.s3.put_object.mock_calls[0][2]['Key'], upload.clone().geometry_key)
        self.assertEqual(
            gzip.decompress(storage.s3.put_object.mock_calls[0][2]['Body']),
            build_blockassign_geojson.return_value.encode('utf8'),
        )

    @unittest.mock.patch('sys.stdout')
    def test_iterate_tile_subtotals(self, stdout):
        ''' Expected counts are returned from tiles.
        '''
        upload = unittest.mock.Mock()
        context = unittest.mock.Mock()
        context.get_remaining_time_in_millis.return_value = 9999
        
        storage = unittest.mock.Mock()
        storage.s3.get_object.side_effect = mock_s3_get_object

        expected_tiles = [f'uploads/sample-plan/tiles/{zxy}.json' for zxy
            in ('12/2047/2047', '12/2047/2048', '12/2048/2047', '12/2048/2048')]
        
        subtotals = list(observe.iterate_tile_subtotals(expected_tiles, storage, upload, context))
        
        self.assertEqual(len(subtotals), 4)
        self.assertEqual(subtotals[0].totals['uploads/sample-plan/geometries/0.wkt']['Voters'], 252.45)
        self.assertEqual(subtotals[1].totals['uploads/sample-plan/geometries/0.wkt']['Voters'], 314.64)
        self.assertNotIn('Voters', subtotals[2].totals['uploads/sample-plan/geometries/0.wkt'])
        self.assertNotIn('Voters', subtotals[3].totals['uploads/sample-plan/geometries/0.wkt'])
        self.assertEqual(subtotals[0].totals['uploads/sample-plan/geometries/1.wkt']['Voters'],  87.2)
        self.assertEqual(subtotals[1].totals['uploads/sample-plan/geometries/1.wkt']['Voters'],  15.94)
        self.assertEqual(subtotals[2].totals['uploads/sample-plan/geometries/1.wkt']['Voters'], 455.99)
        self.assertEqual(subtotals[3].totals['uploads/sample-plan/geometries/1.wkt']['Voters'], 373.76)
    
    @unittest.mock.patch('sys.stdout')
    def test_iterate_tile_totals2(self, stdout):
        ''' Expected counts are returned from tiles.
        '''
        upload = unittest.mock.Mock()
        context = unittest.mock.Mock()
        context.get_remaining_time_in_millis.return_value = 9999
        
        storage = unittest.mock.Mock()
        storage.s3.get_object.side_effect = mock_s3_get_object

        expected_tiles = [f'uploads/sample-plan2/tiles/{zxy}.json' for zxy
            in ('9/255/255', '9/255/256', '9/256/255', '9/256/256')]
        
        tile_totals = list(observe.iterate_tile_subtotals(expected_tiles, storage, upload, context))
        
        self.assertEqual(len(tile_totals), 4)
        self.assertEqual(tile_totals[0].totals['uploads/sample-plan2/geometries/0.wkt']['Voters'], 252.45)
        self.assertEqual(tile_totals[1].totals['uploads/sample-plan2/geometries/0.wkt']['Voters'], 314.64)
        self.assertNotIn('Voters', tile_totals[2].totals['uploads/sample-plan2/geometries/0.wkt'])
        self.assertNotIn('Voters', tile_totals[3].totals['uploads/sample-plan2/geometries/0.wkt'])
        self.assertEqual(tile_totals[0].totals['uploads/sample-plan2/geometries/1.wkt']['Voters'],  87.2)
        self.assertEqual(tile_totals[1].totals['uploads/sample-plan2/geometries/1.wkt']['Voters'],  15.94)
        self.assertEqual(tile_totals[2].totals['uploads/sample-plan2/geometries/1.wkt']['Voters'], 455.99)
        self.assertEqual(tile_totals[3].totals['uploads/sample-plan2/geometries/1.wkt']['Voters'], 373.76)
    
    @unittest.mock.patch('sys.stdout')
    def test_iterate_slice_subtotals(self, stdout):
        ''' Expected counts are returned from slices.
        '''
        upload = unittest.mock.Mock()
        context = unittest.mock.Mock()
        context.get_remaining_time_in_millis.return_value = 9999
        
        storage = unittest.mock.Mock()
        storage.s3.get_object.side_effect = mock_s3_get_object

        expected_slices = ['uploads/sample-plan3/slices/0000000001.json']
        
        subtotals = list(observe.iterate_slice_subtotals(expected_slices, storage, upload, context))
        
        self.assertEqual(len(subtotals), 1)
        self.assertEqual(subtotals[0].totals['uploads/sample-plan3/assignments/0.txt']['Population 2010'], 22)
        self.assertEqual(subtotals[0].totals['uploads/sample-plan3/assignments/1.txt']['Population 2010'], 33)
    
    def test_accumulate_district_subtotals(self):
        '''
        '''
        upload = unittest.mock.Mock()
        upload.id = 'sample-plan'
        inputs = []
        
        for zxy in ('12/2047/2047', '12/2047/2048', '12/2048/2047', '12/2048/2048'):
            tile_key = f'uploads/sample-plan/tiles/{zxy}.json'
            filename = os.path.join(os.path.dirname(__file__), 'data', tile_key)
            with open(filename) as file:
                content = json.load(file)
                inputs.append(observe.SubTotal(
                    content.get('totals'),
                    content.get('timing'),
                ))
        
        upload.districts = [None, None]
        districts1 = observe.accumulate_district_subtotals(inputs, upload)
        
        self.assertEqual(len(districts1), 2)
        self.assertNotIn('compactness', districts1[0])
        self.assertNotIn('compactness', districts1[1])
        self.assertEqual(districts1[0]['totals']['Voters'], 567.09)
        self.assertEqual(districts1[1]['totals']['Voters'], 932.89)
        self.assertEqual(districts1[0]['totals']['Households 2016'], 283.55)
        self.assertEqual(districts1[1]['totals']['Households 2016'], 466.45)
        self.assertAlmostEqual(districts1[0]['totals']['Household Income 2016'], 59000, -1)
        self.assertAlmostEqual(districts1[1]['totals']['Household Income 2016'], 59000, -1)

        upload.districts = [{'compactness': True}, {'compactness': False}]
        districts2 = observe.accumulate_district_subtotals(inputs, upload)
        
        self.assertEqual(len(districts2), 2)
        self.assertTrue(districts2[0]['compactness'])
        self.assertFalse(districts2[1]['compactness'])
        self.assertEqual(districts2[0]['totals']['Voters'], 567.09)
        self.assertEqual(districts2[1]['totals']['Voters'], 932.89)

        upload.districts = [{'totals': {'X': 1}}, {'totals': {'X': 2}}]
        districts3 = observe.accumulate_district_subtotals(inputs, upload)
        
        self.assertEqual(len(districts3), 2)
        self.assertNotIn('compactness', districts3[0])
        self.assertNotIn('compactness', districts3[1])
        self.assertEqual(districts3[0]['totals']['X'], 1)
        self.assertEqual(districts3[1]['totals']['X'], 2)
        self.assertEqual(districts3[0]['totals']['Voters'], 567.09)
        self.assertEqual(districts3[1]['totals']['Voters'], 932.89)
    
    def test_accumulate_district_subtotals_empties(self):
        '''
        '''
        upload = unittest.mock.Mock()
        upload.id = 'sample-plan'
        
        inputs = [
            observe.SubTotal({
                "uploads/sample-plan/geometries/0.wkt": {},
                "uploads/sample-plan/geometries/1.wkt": {
                    "Population 2010": 18,
                    "US President 2016 - DEM": 100,
                    "US President 2016 - REP": 200
                },
            }, {
                "start_time": 1630364292.031,
                "elapsed_time": 0.232,
                "features": 3
            }),
            observe.SubTotal({
                "uploads/sample-plan/geometries/0.wkt": {},
            }, {
                "start_time": 1630364291.918,
                "elapsed_time": 0.271,
                "features": 3
            }),
            observe.SubTotal({
                "uploads/sample-plan/geometries/0.wkt": {},
                "uploads/sample-plan/geometries/1.wkt": {
                    "Population 2010": 4,
                    "US President 2016 - DEM": 0,
                    "US President 2016 - REP": 100
                },
            }, {
                "start_time": 1630364291.997,
                "elapsed_time": 0.259,
                "features": 1
            }),
        ]

        
        upload.districts = [None, None]
        districts = observe.accumulate_district_subtotals(inputs, upload)
        
        self.assertEqual(len(districts), 2)
        self.assertIn('Population 2010', districts[0]['totals'])
        self.assertIn('Population 2010', districts[1]['totals'])
        self.assertIn('US President 2016 - DEM', districts[0]['totals'])
        self.assertIn('US President 2016 - REP', districts[0]['totals'])
        self.assertIn('US President 2016 - DEM', districts[1]['totals'])
        self.assertIn('US President 2016 - REP', districts[1]['totals'])
        self.assertEqual(districts[0]['totals']['Population 2010'], 0)
        self.assertEqual(districts[1]['totals']['Population 2010'], 22)
        self.assertEqual(districts[0]['totals']['US President 2016 - DEM'], 0)
        self.assertEqual(districts[0]['totals']['US President 2016 - REP'], 0)
        self.assertEqual(districts[1]['totals']['US President 2016 - DEM'], 100)
        self.assertEqual(districts[1]['totals']['US President 2016 - REP'], 300)

    def test_adjust_household_income(self):
        '''
        '''
        totals1 = {'Households 2016': 1000, 'Sum Household Income 2016': 59000000}
        totals2 = observe.adjust_household_income(totals1)
        
        self.assertEqual(totals2['Households 2016'], 1000)
        self.assertEqual(totals2['Household Income 2016'], 59000)

        totals3 = {'Households 2016': 1000, 'Voters': 2000}
        totals4 = observe.adjust_household_income(totals3)
        
        self.assertEqual(totals4['Households 2016'], 1000)
        self.assertEqual(totals4['Voters'], 2000)
    
    def test_clean_up_leftover_parts(self):
        '''
        '''
        storage = unittest.mock.Mock()
        tile_keys = ['foo'] * 1001

        observe.clean_up_leftover_parts(storage, tile_keys)
        
        (delete_call1, delete_call2) = storage.s3.delete_objects.mock_calls
        
        self.assertEqual(delete_call1[2],
            dict(Bucket=storage.bucket, Delete={'Objects': [{'Key': 'foo'}] * 1000}))
        
        self.assertEqual(delete_call2[2],
            dict(Bucket=storage.bucket, Delete={'Objects': [{'Key': 'foo'}]}))
